from flask import Blueprint, request, session, redirect, url_for, render_template, flash, current_app, jsonify, Response
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect, CSRFError
from wtforms import FloatField, IntegerField, SubmitField, StringField, FieldList, FormField
from wtforms.validators import DataRequired, NumberRange, ValidationError, Optional, Length
from flask_login import current_user, login_required
import utils
from utils import logger
from datetime import datetime
import re
from translations import trans
from bson import ObjectId
from models import log_tool_usage, create_budget
from helpers.transaction_helpers import create_budget_allocation_transaction
import uuid
import bleach
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from io import BytesIO
from helpers.branding_helpers import draw_ficore_pdf_header

budget_bp = Blueprint(
    'budget',
    __name__,
    template_folder='templates/',
    url_prefix='/budget'
)

def clean_currency(value):
    """Transform input into a float, using improved validation from utils."""
    try:
        return utils.clean_currency(value)
    except Exception:
        return 0.0

def strip_commas(value):
    """Filter to remove commas and return a float."""
    return clean_currency(value)

def format_currency(value):
    """Format a numeric value with comma separation, no currency symbol."""
    try:
        numeric_value = float(value)
        formatted = f"{numeric_value:,.2f}"
        return formatted
    except (ValueError, TypeError):
        return "0.00"

def custom_login_required(f):
    """Custom login decorator that requires authentication."""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.is_authenticated:
            return f(*args, **kwargs)
        flash(trans('general_login_required', default='Please log in to access this page.'), 'warning')
        return redirect(url_for('users.login', next=request.url))
    return decorated_function

def deduct_ficore_credits(db, user_id, amount, action, budget_id=None):
    """
    Deduct Ficore Credits from user balance with enhanced error logging and transaction handling.
    
    Args:
        db: MongoDB database instance
        user_id: User ID (must match _id field in users collection)
        amount: Amount to deduct
        action: Action description for logging
        budget_id: Optional budget ID for reference
    
    Returns:
        bool: True if successful, False otherwise
    """
    session_id = session.get('sid', 'unknown')
    
    try:
        # Validate input parameters
        if not user_id:
            logger.error(f"No user_id provided for credit deduction, action: {action}",
                        extra={'session_id': session_id})
            return False
        
        if amount <= 0:
            logger.error(f"Invalid deduction amount {amount} for user {user_id}, action: {action}. Must be positive.",
                        extra={'session_id': session_id, 'user_id': user_id})
            return False
        
        # Check if user exists and get current balance
        user = db.users.find_one({'_id': user_id})
        if not user:
            logger.error(f"User {user_id} not found in database for credit deduction, action: {action}. Check if user_id matches _id field type.",
                        extra={'session_id': session_id, 'user_id': user_id})
            return False
        
        current_balance = float(user.get('ficore_credit_balance', 0))
        logger.debug(f"Current balance for user {user_id}: {current_balance}, attempting to deduct: {amount}",
                    extra={'session_id': session_id, 'user_id': user_id})
        
        if current_balance < amount:
            logger.warning(f"Insufficient credits for user {user_id}: required {amount}, available {current_balance}, action: {action}",
                         extra={'session_id': session_id, 'user_id': user_id})
            return False
        
        # Use transaction for atomic operation
        with db.client.start_session() as mongo_session:
            with mongo_session.start_transaction():
                # Update user balance using $inc to maintain atomicity
                result = db.users.update_one(
                    {'_id': user_id},
                    {'$inc': {'ficore_credit_balance': -amount}},
                    session=mongo_session
                )
                
                if result.modified_count == 0:
                    error_msg = f"Failed to deduct {amount} credits for user {user_id}, action: {action}: No documents modified. User may not exist or balance unchanged."
                    logger.error(error_msg, extra={'session_id': session_id, 'user_id': user_id})
                    
                    # Log failed transaction
                    db.ficore_credit_transactions.insert_one({
                        '_id': ObjectId(),
                        'user_id': user_id,
                        'action': action,
                        'amount': float(-amount),
                        'budget_id': str(budget_id) if budget_id else None,
                        'timestamp': datetime.utcnow(),
                        'session_id': session_id,
                        'status': 'failed'
                    }, session=mongo_session)
                    
                    raise ValueError(error_msg)
                
                # Log successful transaction
                transaction = {
                    '_id': ObjectId(),
                    'user_id': user_id,
                    'action': action,
                    'amount': float(-amount),
                    'budget_id': str(budget_id) if budget_id else None,
                    'timestamp': datetime.utcnow(),
                    'session_id': session_id,
                    'status': 'completed'
                }
                db.ficore_credit_transactions.insert_one(transaction, session=mongo_session)
                
                # Log audit trail
                db.audit_logs.insert_one({
                    'admin_id': 'system',
                    'action': f'deduct_ficore_credits_{action}',
                    'details': {
                        'user_id': user_id,
                        'amount': amount,
                        'budget_id': str(budget_id) if budget_id else None,
                        'previous_balance': current_balance,
                        'new_balance': current_balance - amount
                    },
                    'timestamp': datetime.utcnow()
                }, session=mongo_session)
                
                mongo_session.commit_transaction()
                
        logger.info(f"Successfully deducted {amount} Ficore Credits for {action} by user {user_id}. New balance: {current_balance - amount}",
                   extra={'session_id': session_id, 'user_id': user_id})
        return True
        
    except Exception as e:
        logger.error(f"Error deducting {amount} Ficore Credits for {action} by user {user_id}: {str(e)}",
                    exc_info=True, extra={'session_id': session_id, 'user_id': user_id})
        return False

class BudgetItemForm(FlaskForm):
    name = StringField(
        trans('budget_item_name', default='Item Name'),
        validators=[
            DataRequired(message=trans('budget_item_name_required', default='Item name is required')),
            Length(min=2, max=50, message=trans('budget_item_name_length', default='Item name must be between 2 and 50 characters'))
        ]
    )
    amount = FloatField(
        trans('budget_item_amount', default='Amount'),
        filters=[strip_commas],
        validators=[
            DataRequired(message=trans('budget_item_amount_required', default='Amount is required')),
            NumberRange(min=0.01, max=10000000000, message=trans('budget_amount_max', default='Amount must be between 0.01 and 10 billion'))
        ]
    )
    note = StringField(
        trans('budget_item_note', default='Note (Optional)'),
        validators=[
            Optional(),
            Length(max=200, message=trans('budget_item_note_length', default='Note must be less than 200 characters'))
        ]
    )
    
    class Meta:
        csrf = False  # Disable CSRF for subform, as it's handled by the parent BudgetForm

class CommaSeparatedIntegerField(IntegerField):
    def process_formdata(self, valuelist):
        if valuelist:
            try:
                cleaned_value = clean_currency(valuelist[0])
                self.data = int(cleaned_value) if cleaned_value is not None else None
            except (ValueError, TypeError):
                self.data = None
                raise ValidationError(trans('budget_dependents_invalid', default='Not a valid integer'))

class BudgetForm(FlaskForm):
    budget_name = StringField(
        trans('budget_name', default='Budget Name'),
        validators=[
            Optional(),
            Length(min=2, max=100, message=trans('budget_name_length', default='Budget name must be between 2 and 100 characters'))
        ]
    )
    
    # Income items
    income_items = FieldList(
        FormField(BudgetItemForm),
        min_entries=0,
        max_entries=20,
        validators=[Optional()]
    )
    
    # Expense items
    expense_items = FieldList(
        FormField(BudgetItemForm),
        min_entries=0,
        max_entries=20,
        validators=[Optional()]
    )
    
    # Investment items (new category)
    investment_items = FieldList(
        FormField(BudgetItemForm),
        min_entries=0,
        max_entries=20,
        validators=[Optional()]
    )
    
    # Savings items (separate from investments)
    savings_items = FieldList(
        FormField(BudgetItemForm),
        min_entries=0,
        max_entries=20,
        validators=[Optional()]
    )
    
    # Supports & Dependents items (new category)
    dependents_items = FieldList(
        FormField(BudgetItemForm),
        min_entries=0,
        max_entries=20,
        validators=[Optional()]
    )
    
    submit = SubmitField(trans('budget_submit', default='Submit'))
    
    # Legacy fields for backward compatibility
    income = FloatField(validators=[Optional()])
    housing = FloatField(validators=[Optional()])
    food = FloatField(validators=[Optional()])
    transport = FloatField(validators=[Optional()])
    dependents = CommaSeparatedIntegerField(validators=[Optional()])
    miscellaneous = FloatField(validators=[Optional()])
    others = FloatField(validators=[Optional()])
    savings_goal = FloatField(validators=[Optional()])
    custom_categories = FieldList(FormField(BudgetItemForm), validators=[Optional()])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        lang = session.get('lang', 'en')
        self.budget_name.label.text = trans('budget_name', lang) or 'Budget Name'
        self.submit.label.text = trans('budget_submit', lang) or 'Submit'

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators):
            logger.debug(f"Form validation failed: {self.errors}", extra={'session_id': session.get('sid', 'unknown')})
            return False
        try:
            # Validate unique item names within each category
            for category_name, items in [
                ('income', self.income_items.entries),
                ('expense', self.expense_items.entries),
                ('investment', self.investment_items.entries),
                ('savings', self.savings_items.entries),
                ('dependents', self.dependents_items.entries)
            ]:
                item_names = []
                for item in items:
                    if not isinstance(item.form, BudgetItemForm):
                        logger.warning(f"Invalid entry in {category_name}_items: {item.__dict__}",
                                      extra={'session_id': session.get('sid', 'unknown')})
                        getattr(self, f'{category_name}_items').errors.append(
                            trans('budget_invalid_item', default=f'Invalid {category_name} item format')
                        )
                        return False
                    if item.form.name.data and item.form.amount.data:
                        item_names.append(item.form.name.data.lower())
                
                if len(item_names) != len(set(item_names)):
                    getattr(self, f'{category_name}_items').errors.append(
                        trans('budget_duplicate_item_names', default=f'{category_name.title()} item names must be unique')
                    )
                    return False
            
            return True
        except Exception as e:
            logger.error(f"Error in BudgetForm.validate: {str(e)}",
                        exc_info=True, extra={'session_id': session.get('sid', 'unknown')})
            self.income_items.errors.append(
                trans('budget_validation_error', default='Error validating budget data.')
            )
            return False

@budget_bp.route('/', methods=['GET'])
@custom_login_required
@utils.requires_role(['personal', 'admin'])
def index():
    """Budget module landing page with navigation cards."""
    return render_template('budget/index.html')

@budget_bp.route('/new', methods=['GET', 'POST'])
@custom_login_required
@utils.requires_role(['personal', 'admin'])
@utils.limiter.limit("10 per minute")
def new():
    session.permanent = False
    session_id = session.get('sid', str(uuid.uuid4()))
    session['sid'] = session_id
    current_app.logger.debug(f"Session data: {session}", extra={'session_id': session_id})
    
    form = BudgetForm(formdata=request.form if request.method == 'POST' else None)
    db = utils.get_mongo_db()

    valid_tabs = ['create-budget', 'dashboard']
    active_tab = request.args.get('tab', 'create-budget')
    if active_tab not in valid_tabs:
        active_tab = 'create-budget'

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json

    try:
        log_tool_usage(
            tool_name='budget',
            db=db,
            user_id=current_user.id,
            session_id=session_id,
            action='main_view'
        )
    except Exception as e:
        current_app.logger.error(f"Failed to log tool usage: {str(e)}", extra={'session_id': session_id})
        flash(trans('budget_log_error', default='Error logging budget activity. Please try again.'), 'warning')

    try:
        activities = utils.get_all_recent_activities(
            db=db,
            user_id=current_user.id,
            session_id=None,
        )
        current_app.logger.debug(f"Fetched {len(activities)} recent activities for user {current_user.id}", extra={'session_id': session_id})
    except Exception as e:
        current_app.logger.error(f"Failed to fetch recent activities: {str(e)}", extra={'session_id': session_id})
        flash(trans('budget_activities_load_error', default='Error loading recent activities.'), 'warning')
        activities = []

    try:
        filter_criteria = {} if utils.is_admin() else {'user_id': current_user.id}
        if request.method == 'POST':
            current_app.logger.debug(f"POST request.form: {dict(request.form)}", extra={'session_id': session_id})
            current_app.logger.debug(f"CSRF token in request.form: {'csrf_token' in request.form}", extra={'session_id': session_id})
            if not form.validate_on_submit():
                current_app.logger.debug(f"Form errors: {form.errors}", extra={'session_id': session_id})
                error_message = trans('budget_form_invalid', default='Invalid form data. Please check your inputs.')
                if is_ajax:
                    return jsonify({'success': False, 'message': error_message, 'errors': form.errors}), 400
                flash(error_message, 'danger')
                return render_template(
                    'budget/new.html',
                    form=form,
                    budgets={},
                    latest_budget={
                        'id': None,
                        'user_id': None,
                        'session_id': session_id,
                        'user_email': current_user.email,
                        'income': format_currency(0.0),
                        'income_raw': 0.0,
                        'fixed_expenses': format_currency(0.0),
                        'fixed_expenses_raw': 0.0,
                        'variable_expenses': format_currency(0.0),
                        'variable_expenses_raw': 0.0,
                        'total_expenses': format_currency(0.0),
                        'total_expenses_raw': 0.0,
                        'savings_goal': format_currency(0.0),
                        'savings_goal_raw': 0.0,
                        'surplus_deficit': 0.0,
                        'surplus_deficit_formatted': format_currency(0.0),
                        'housing': format_currency(0.0),
                        'housing_raw': 0.0,
                        'food': format_currency(0.0),
                        'food_raw': 0.0,
                        'transport': format_currency(0.0),
                        'transport_raw': 0.0,
                        'dependents': str(0),
                        'dependents_raw': 0,
                        'miscellaneous': format_currency(0.0),
                        'miscellaneous_raw': 0.0,
                        'others': format_currency(0.0),
                        'others_raw': 0.0,
                        'custom_categories': [],
                        'created_at': 'N/A'
                    },
                    categories={},
                    tips=[],
                    insights=[],
                    activities=activities,
                    tool_title=trans('budget_title', default='Budget Planner'),
                    active_tab=active_tab
                ), 400

            action = request.form.get('action')
            if action == 'create_budget' and form.validate_on_submit():
                if current_user.is_authenticated and not utils.is_admin():
                    if not utils.check_ficore_credit_balance(required_amount=1, user_id=current_user.id):
                        current_app.logger.warning(f"Insufficient Ficore Credits for creating budget by user {current_user.id}", extra={'session_id': session_id})
                        error_message = trans('budget_insufficient_credits', default='Insufficient Ficore Credits to create a budget. Please purchase more credits.')
                        if is_ajax:
                            return jsonify({'success': False, 'message': error_message}), 400
                        flash(error_message, 'danger')
                        return redirect(url_for('dashboard.index'))

                try:
                    log_tool_usage(
                        tool_name='budget',
                        db=db,
                        user_id=current_user.id,
                        session_id=session_id,
                        action='create_budget'
                    )
                except Exception as e:
                    current_app.logger.error(f"Failed to log budget creation: {str(e)}", extra={'session_id': session_id})
                    flash(trans('budget_log_error', default='Error logging budget creation. Continuing with submission.'), 'warning')

                # Process new item-based structure
                income_items = []
                total_income = 0.0
                for item in form.income_items.entries:
                    if item.form.name.data and item.form.amount.data:
                        income_item = {
                            'name': bleach.clean(item.form.name.data),
                            'amount': float(item.form.amount.data),
                            'note': bleach.clean(item.form.note.data) if item.form.note.data else None
                        }
                        income_items.append(income_item)
                        total_income += income_item['amount']

                expense_items = []
                total_expenses = 0.0
                for item in form.expense_items.entries:
                    if item.form.name.data and item.form.amount.data:
                        expense_item = {
                            'name': bleach.clean(item.form.name.data),
                            'amount': float(item.form.amount.data),
                            'note': bleach.clean(item.form.note.data) if item.form.note.data else None
                        }
                        expense_items.append(expense_item)
                        total_expenses += expense_item['amount']

                investment_items = []
                total_investments = 0.0
                for item in form.investment_items.entries:
                    if item.form.name.data and item.form.amount.data:
                        investment_item = {
                            'name': bleach.clean(item.form.name.data),
                            'amount': float(item.form.amount.data),
                            'note': bleach.clean(item.form.note.data) if item.form.note.data else None
                        }
                        investment_items.append(investment_item)
                        total_investments += investment_item['amount']

                savings_items = []
                total_savings = 0.0
                for item in form.savings_items.entries:
                    if item.form.name.data and item.form.amount.data:
                        savings_item = {
                            'name': bleach.clean(item.form.name.data),
                            'amount': float(item.form.amount.data),
                            'note': bleach.clean(item.form.note.data) if item.form.note.data else None
                        }
                        savings_items.append(savings_item)
                        total_savings += savings_item['amount']

                dependents_items = []
                total_dependents = 0.0
                for item in form.dependents_items.entries:
                    if item.form.name.data and item.form.amount.data:
                        dependents_item = {
                            'name': bleach.clean(item.form.name.data),
                            'amount': float(item.form.amount.data),
                            'note': bleach.clean(item.form.note.data) if item.form.note.data else None
                        }
                        dependents_items.append(dependents_item)
                        total_dependents += dependents_item['amount']

                # Calculate surplus/deficit
                surplus_deficit = total_income - total_expenses - total_investments - total_savings - total_dependents
                
                budget_id = ObjectId()
                budget_data = {
                    '_id': budget_id,
                    'user_id': current_user.id,
                    'session_id': session_id,
                    'budget_name': bleach.clean(form.budget_name.data) if form.budget_name.data else None,
                    'income_items': income_items,
                    'expense_items': expense_items,
                    'investment_items': investment_items,
                    'savings_items': savings_items,
                    'dependents_items': dependents_items,
                    'total_income': total_income,
                    'total_expenses': total_expenses,
                    'total_investments': total_investments,
                    'total_savings': total_savings,
                    'total_dependents': total_dependents,
                    'surplus_deficit': surplus_deficit,
                    'created_at': datetime.utcnow(),
                    # Legacy fields for backward compatibility
                    'income': total_income,
                    'fixed_expenses': total_expenses,
                    'variable_expenses': 0.0,
                    'savings_goal': total_savings,
                    'housing': 0.0,
                    'food': 0.0,
                    'transport': 0.0,
                    'dependents': int(total_dependents),  # Legacy field as integer count
                    'miscellaneous': 0.0,
                    'others': 0.0,
                    'custom_categories': []
                }
                current_app.logger.debug(f"Saving budget data: {budget_data}", extra={'session_id': session_id})
                try:
                    with db.client.start_session() as mongo_session:
                        with mongo_session.start_transaction():
                            created_budget_id = create_budget(db, budget_data)
                            
                            # Create transaction records for budget allocations
                            try:
                                budget_with_id = budget_data.copy()
                                budget_with_id['_id'] = created_budget_id
                                
                                # Create transactions for each budget category with non-zero amounts
                                if budget_data.get('income', 0) > 0:
                                    create_budget_allocation_transaction(db, budget_with_id, 'income', budget_data['income'], 'Budget Income Allocation', session_id)
                                if budget_data.get('housing', 0) > 0:
                                    create_budget_allocation_transaction(db, budget_with_id, 'expense', budget_data['housing'], 'Housing Budget', session_id)
                                if budget_data.get('food', 0) > 0:
                                    create_budget_allocation_transaction(db, budget_with_id, 'expense', budget_data['food'], 'Food Budget', session_id)
                                if budget_data.get('transportation', 0) > 0:
                                    create_budget_allocation_transaction(db, budget_with_id, 'expense', budget_data['transportation'], 'Transportation Budget', session_id)
                                if budget_data.get('entertainment', 0) > 0:
                                    create_budget_allocation_transaction(db, budget_with_id, 'expense', budget_data['entertainment'], 'Entertainment Budget', session_id)
                                if budget_data.get('savings', 0) > 0:
                                    create_budget_allocation_transaction(db, budget_with_id, 'savings', budget_data['savings'], 'Savings Allocation', session_id)
                                if budget_data.get('investments', 0) > 0:
                                    create_budget_allocation_transaction(db, budget_with_id, 'investment', budget_data['investments'], 'Investment Allocation', session_id)
                                if budget_data.get('others', 0) > 0:
                                    create_budget_allocation_transaction(db, budget_with_id, 'expense', budget_data['others'], 'Other Expenses Budget', session_id)
                            except Exception as e:
                                current_app.logger.warning(f"Failed to create budget allocation transactions: {str(e)}", extra={'session_id': session_id})
                            
                            if current_user.is_authenticated and not utils.is_admin():
                                if not deduct_ficore_credits(db, current_user.id, 1, 'create_budget', budget_id):
                                    db.budgets.delete_one({'_id': budget_id}, session=mongo_session)
                                    raise ValueError("Credit deduction failed")
                            mongo_session.commit_transaction()
                    current_app.logger.info(f"Budget {created_budget_id} saved successfully to MongoDB for session {session_id}", extra={'session_id': session_id})
                    # Move cache clearing outside transaction
                    try:
                        caching_ext = current_app.extensions.get('caching')
                        if caching_ext:
                            cache = list(caching_ext.values())[0]
                            cache.delete_memoized(utils.get_budgets)
                            current_app.logger.debug(f"Cleared cache for get_budgets", extra={'session_id': session_id})
                        else:
                            current_app.logger.warning(f"Caching extension not found; skipping cache clear", extra={'session_id': session_id})
                    except Exception as e:
                        current_app.logger.warning(f"Failed to clear cache for get_budgets: {str(e)}", extra={'session_id': session_id})

                    success_message = trans("general_budget_created", default='Budget created successfully!')
                    if is_ajax:
                        return jsonify({'success': True, 'budget_id': str(created_budget_id), 'message': success_message}), 200
                    flash(success_message, "success")
                    return redirect(url_for('budget.dashboard'))
                except Exception as e:
                    current_app.logger.error(f"Failed to save budget {budget_id} to MongoDB for session {session_id}: {str(e)}", extra={'session_id': session_id})
                    error_message = trans("budget_storage_error", default='Error saving budget.')
                    if is_ajax:
                        return jsonify({'success': False, 'message': error_message}), 500
                    flash(error_message, "danger")
                    return render_template(
                        'budget/new.html',
                        form=form,
                        budgets={},
                        latest_budget={
                            'id': None,
                            'user_id': None,
                            'session_id': session_id,
                            'user_email': current_user.email,
                            'income': format_currency(0.0),
                            'income_raw': 0.0,
                            'fixed_expenses': format_currency(0.0),
                            'fixed_expenses_raw': 0.0,
                            'variable_expenses': format_currency(0.0),
                            'variable_expenses_raw': 0.0,
                            'total_expenses': format_currency(0.0),
                            'total_expenses_raw': 0.0,
                            'savings_goal': format_currency(0.0),
                            'savings_goal_raw': 0.0,
                            'surplus_deficit': 0.0,
                            'surplus_deficit_formatted': format_currency(0.0),
                            'housing': format_currency(0.0),
                            'housing_raw': 0.0,
                            'food': format_currency(0.0),
                            'food_raw': 0.0,
                            'transport': format_currency(0.0),
                            'transport_raw': 0.0,
                            'dependents': str(0),
                            'dependents_raw': 0,
                            'miscellaneous': format_currency(0.0),
                            'miscellaneous_raw': 0.0,
                            'others': format_currency(0.0),
                            'others_raw': 0.0,
                            'custom_categories': [],
                            'created_at': 'N/A'
                        },
                        categories={},
                        tips=[],
                        insights=[],
                        activities=activities,
                        tool_title=trans('budget_title', default='Budget Planner'),
                        active_tab=active_tab
                    )
            elif action == 'delete':
                budget_id = request.form.get('budget_id')
                budget = db.budgets.find_one({'_id': ObjectId(budget_id), **filter_criteria})
                if not budget:
                    current_app.logger.warning(f"Budget {budget_id} not found for deletion", extra={'session_id': session_id})
                    error_message = trans("budget_not_found", default='Budget not found.')
                    if is_ajax:
                        return jsonify({'success': False, 'message': error_message}), 404
                    flash(error_message, "danger")
                    return redirect(url_for('budget.manage'))
                if current_user.is_authenticated and not utils.is_admin():
                    if not utils.check_ficore_credit_balance(required_amount=1, user_id=current_user.id):
                        current_app.logger.warning(f"Insufficient Ficore Credits for deleting budget {budget_id} by user {current_user.id}", extra={'session_id': session_id})
                        error_message = trans('budget_insufficient_credits', default='Insufficient Ficore Credits to delete a budget. Please purchase more credits.')
                        if is_ajax:
                            return jsonify({'success': False, 'message': error_message}), 400
                        flash(error_message, 'danger')
                        return redirect(url_for('dashboard.index'))
                try:
                    with db.client.start_session() as mongo_session:
                        with mongo_session.start_transaction():
                            result = db.budgets.delete_one({'_id': ObjectId(budget_id), **filter_criteria}, session=mongo_session)
                            if result.deleted_count > 0:
                                if current_user.is_authenticated and not utils.is_admin():
                                    if not deduct_ficore_credits(db, current_user.id, 1, 'delete_budget', budget_id):
                                        error_message = trans('budget_credit_deduction_failed', default='Failed to deduct Ficore Credit for deleting budget.')
                                        if is_ajax:
                                            return jsonify({'success': False, 'message': error_message}), 400
                                        flash(error_message, 'danger')
                                        return redirect(url_for('budget.manage'))
                                mongo_session.commit_transaction()
                            else:
                                current_app.logger.warning(f"Budget ID {budget_id} not found for session {session_id}", extra={'session_id': session_id})
                                error_message = trans("budget_not_found", default='Budget not found.')
                                if is_ajax:
                                    return jsonify({'success': False, 'message': error_message}), 404
                                flash(error_message, "danger")
                                return redirect(url_for('budget.manage'))
                    try:
                        caching_ext = current_app.extensions.get('caching')
                        if caching_ext:
                            cache = list(caching_ext.values())[0]
                            cache.delete_memoized(utils.get_budgets)
                            current_app.logger.debug(f"Cleared cache for get_budgets", extra={'session_id': session_id})
                        else:
                            current_app.logger.warning(f"Caching extension not found; skipping cache clear", extra={'session_id': session_id})
                    except Exception as e:
                        current_app.logger.warning(f"Failed to clear cache for get_budgets: {str(e)}", extra={'session_id': session_id})
                    current_app.logger.info(f"Deleted budget ID {budget_id} for session {session_id}", extra={'session_id': session_id})
                    success_message = trans("budget_deleted_success", default='Budget deleted successfully!')
                    if is_ajax:
                        return jsonify({'success': True, 'message': success_message}), 200
                    flash(success_message, "success")
                    return redirect(url_for('budget.manage'))
                except Exception as e:
                    current_app.logger.error(f"Failed to delete budget ID {budget_id} for session {session_id}: {str(e)}", extra={'session_id': session_id})
                    error_message = trans("budget_delete_failed", default='Error deleting budget.')
                    if is_ajax:
                        return jsonify({'success': False, 'message': error_message}), 500
                    flash(error_message, "danger")
                    return redirect(url_for('budget.manage'))

        budgets = list(db.budgets.find(filter_criteria).sort('created_at', -1).limit(10))
        current_app.logger.info(f"Read {len(budgets)} records from MongoDB budgets collection [session: {session_id}]", extra={'session_id': session_id})
        budgets_dict = {}
        latest_budget = None
        for budget in budgets:
            fixed_raw = float(budget.get('fixed_expenses', 0.0))
            var_raw = float(budget.get('variable_expenses', 0.0))
            total_raw = fixed_raw + var_raw
            budget_data = {
                'id': str(budget['_id']),
                'user_id': budget.get('user_id'),
                'session_id': budget.get('session_id'),
                'user_email': budget.get('user_email', current_user.email),
                'income': format_currency(budget.get('income', 0.0)),
                'income_raw': float(budget.get('income', 0.0)),
                'fixed_expenses': format_currency(fixed_raw),
                'fixed_expenses_raw': fixed_raw,
                'variable_expenses': format_currency(var_raw),
                'variable_expenses_raw': var_raw,
                'total_expenses': format_currency(total_raw),
                'total_expenses_raw': total_raw,
                'savings_goal': format_currency(budget.get('savings_goal', 0.0)),
                'savings_goal_raw': float(budget.get('savings_goal', 0.0)),
                'surplus_deficit': float(budget.get('surplus_deficit', 0.0)),
                'surplus_deficit_formatted': format_currency(budget.get('surplus_deficit', 0.0)),
                'housing': format_currency(budget.get('housing', 0.0)),
                'housing_raw': float(budget.get('housing', 0.0)),
                'food': format_currency(budget.get('food', 0.0)),
                'food_raw': float(budget.get('food', 0.0)),
                'transport': format_currency(budget.get('transport', 0.0)),
                'transport_raw': float(budget.get('transport', 0.0)),
                'dependents': str(budget.get('dependents', 0)),
                'dependents_raw': int(budget.get('dependents', 0)),
                'miscellaneous': format_currency(budget.get('miscellaneous', 0.0)),
                'miscellaneous_raw': float(budget.get('miscellaneous', 0.0)),
                'others': format_currency(budget.get('others', 0.0)),
                'others_raw': float(budget.get('others', 0.0)),
                'custom_categories': budget.get('custom_categories', []),
                'created_at': budget.get('created_at').strftime('%Y-%m-%d') if budget.get('created_at') else 'N/A'
            }
            budgets_dict[budget_data['id']] = budget_data
            if not latest_budget or (budget.get('created_at') and (latest_budget['created_at'] == 'N/A' or budget.get('created_at') > datetime.strptime(latest_budget['created_at'], '%Y-%m-%d'))):
                latest_budget = budget_data
        if not latest_budget:
            latest_budget = {
                'id': None,
                'user_id': None,
                'session_id': session_id,
                'user_email': current_user.email,
                'income': format_currency(0.0),
                'income_raw': 0.0,
                'fixed_expenses': format_currency(0.0),
                'fixed_expenses_raw': 0.0,
                'variable_expenses': format_currency(0.0),
                'variable_expenses_raw': 0.0,
                'total_expenses': format_currency(0.0),
                'total_expenses_raw': 0.0,
                'savings_goal': format_currency(0.0),
                'savings_goal_raw': 0.0,
                'surplus_deficit': 0.0,
                'surplus_deficit_formatted': format_currency(0.0),
                'housing': format_currency(0.0),
                'housing_raw': 0.0,
                'food': format_currency(0.0),
                'food_raw': 0.0,
                'transport': format_currency(0.0),
                'transport_raw': 0.0,
                'dependents': str(0),
                'dependents_raw': 0,
                'miscellaneous': format_currency(0.0),
                'miscellaneous_raw': 0.0,
                'others': format_currency(0.0),
                'others_raw': 0.0,
                'custom_categories': [],
                'created_at': 'N/A'
            }
        categories = {
            trans('budget_housing_rent', default='Housing/Rent'): latest_budget.get('housing_raw', 0.0),
            trans('budget_food', default='Food'): latest_budget.get('food_raw', 0.0),
            trans('budget_transport', default='Transport'): latest_budget.get('transport_raw', 0.0),
            trans('budget_miscellaneous', default='Miscellaneous'): latest_budget.get('miscellaneous_raw', 0.0),
            trans('budget_others', default='Others'): latest_budget.get('others_raw', 0.0),
        }
        for cat in latest_budget.get('custom_categories', []):
            categories[cat['name']] = cat['amount']
        categories = {k: v for k, v in categories.items() if v > 0}
        tips = [
            trans("budget_tip_track_expenses", default='Track your expenses daily to stay within budget.'),
            trans("budget_tip_ajo_savings", default='Contribute to ajo savings for financial discipline.'),
            trans("budget_tip_data_subscriptions", default='Optimize data subscriptions to reduce costs.'),
            trans("budget_tip_plan_dependents", default='Plan for dependents’ expenses in advance.')
        ]
        insights = []
        try:
            income_float = float(latest_budget.get('income_raw', 0.0))
            surplus_deficit_float = float(latest_budget.get('surplus_deficit', 0.0))
            savings_goal_float = float(latest_budget.get('savings_goal_raw', 0.0))
            if income_float > 0:
                if surplus_deficit_float < 0:
                    insights.append(trans("budget_insight_budget_deficit", default='Your expenses exceed your income. Consider reducing costs.'))
                elif surplus_deficit_float > 0:
                    insights.append(trans("budget_insight_budget_surplus", default='You have a surplus. Consider increasing savings.'))
                if savings_goal_float == 0:
                    insights.append(trans("budget_insight_set_savings_goal", default='Set a savings goal to build financial security.'))
                if income_float > 0 and latest_budget.get('housing_raw', 0.0) / income_float > 0.4:
                    insights.append(trans("budget_insight_high_housing", default='Housing costs exceed 40% of income. Consider cost-saving measures.'))
        except (ValueError, TypeError) as e:
            current_app.logger.warning(f"Error parsing budget amounts for insights: {str(e)}", extra={'session_id': session_id})
        current_app.logger.debug(f"Rendering template with context: form={form}, budgets={budgets_dict}, latest_budget={latest_budget}, categories={categories}, active_tab={active_tab}", extra={'session_id': session_id})
        return render_template(
            'budget/new.html',
            form=form,
            budgets=budgets_dict,
            latest_budget=latest_budget,
            categories=categories,
            tips=tips,
            insights=insights,
            activities=activities,
            tool_title=trans('budget_title', default='Budget Planner'),
            active_tab=active_tab
        )
    except Exception as e:
        current_app.logger.exception(f"Unexpected error in budget.main active_tab: {active_tab}", extra={'session_id': session_id})
        error_message = trans('budget_dashboard_load_error', default='Error loading budget dashboard.')
        if is_ajax:
            return jsonify({'success': False, 'message': error_message}), 500
        flash(error_message, 'danger')
        return render_template(
            'budget/new.html',
            form=form,
            budgets={},
            latest_budget={
                'id': None,
                'user_id': None,
                'session_id': session_id,
                'user_email': current_user.email if current_user.is_authenticated else '',
                'income': format_currency(0.0),
                'income_raw': 0.0,
                'fixed_expenses': format_currency(0.0),
                'fixed_expenses_raw': 0.0,
                'variable_expenses': format_currency(0.0),
                'variable_expenses_raw': 0.0,
                'total_expenses': format_currency(0.0),
                'total_expenses_raw': 0.0,
                'savings_goal': format_currency(0.0),
                'savings_goal_raw': 0.0,
                'surplus_deficit': 0.0,
                'surplus_deficit_formatted': format_currency(0.0),
                'housing': format_currency(0.0),
                'housing_raw': 0.0,
                'food': format_currency(0.0),
                'food_raw': 0.0,
                'transport': format_currency(0.0),
                'transport_raw': 0.0,
                'dependents': str(0),
                'dependents_raw': 0,
                'miscellaneous': format_currency(0.0),
                'miscellaneous_raw': 0.0,
                'others': format_currency(0.0),
                'others_raw': 0.0,
                'custom_categories': [],
                'created_at': 'N/A'
            },
            categories={},
            tips=[],
            insights=[],
            activities=activities,
            tool_title=trans('budget_title', default='Budget Planner'),
            active_tab=active_tab
        ), 500

@budget_bp.route('/dashboard', methods=['GET'])
@custom_login_required
@utils.requires_role(['personal', 'admin'])
@utils.limiter.limit("10 per minute")
def dashboard():
    """Budget dashboard page."""
    if 'sid' not in session:
        session['sid'] = str(uuid.uuid4())
        current_app.logger.debug(f"New session created with sid: {session['sid']}", extra={'session_id': session['sid']})
    session.permanent = False
    session.modified = True
    db = utils.get_mongo_db()

    try:
        log_tool_usage(
            tool_name='budget',
            db=db,
            user_id=current_user.id,
            session_id=session.get('sid', 'unknown'),
            action='dashboard_view'
        )
    except Exception as e:
        current_app.logger.error(f"Failed to log tool usage: {str(e)}", extra={'session_id': session.get('sid', 'unknown')})
        flash(trans('budget_log_error', default='Error logging budget activity. Please try again.'), 'warning')

    try:
        activities = utils.get_all_recent_activities(
            db=db,
            user_id=current_user.id,
            session_id=None,
        )
    except Exception as e:
        current_app.logger.error(f"Failed to fetch recent activities: {str(e)}", extra={'session_id': session.get('sid', 'unknown')})
        flash(trans('budget_activities_load_error', default='Error loading recent activities.'), 'warning')
        activities = []

    try:
        filter_criteria = {} if utils.is_admin() else {'user_id': current_user.id}
        budgets = list(db.budgets.find(filter_criteria).sort('created_at', -1).limit(10))
        
        budgets_dict = {}
        latest_budget = None
        for budget in budgets:
            fixed_raw = float(budget.get('fixed_expenses', 0.0))
            var_raw = float(budget.get('variable_expenses', 0.0))
            total_raw = fixed_raw + var_raw
            budget_data = {
                'id': str(budget['_id']),
                'user_id': budget.get('user_id'),
                'session_id': budget.get('session_id'),
                'user_email': budget.get('user_email', current_user.email),
                'income': format_currency(budget.get('income', 0.0)),
                'income_raw': float(budget.get('income', 0.0)),
                'fixed_expenses': format_currency(fixed_raw),
                'fixed_expenses_raw': fixed_raw,
                'variable_expenses': format_currency(var_raw),
                'variable_expenses_raw': var_raw,
                'total_expenses': format_currency(total_raw),
                'total_expenses_raw': total_raw,
                'savings_goal': format_currency(budget.get('savings_goal', 0.0)),
                'savings_goal_raw': float(budget.get('savings_goal', 0.0)),
                'surplus_deficit': float(budget.get('surplus_deficit', 0.0)),
                'surplus_deficit_formatted': format_currency(budget.get('surplus_deficit', 0.0)),
                'housing': format_currency(budget.get('housing', 0.0)),
                'housing_raw': float(budget.get('housing', 0.0)),
                'food': format_currency(budget.get('food', 0.0)),
                'food_raw': float(budget.get('food', 0.0)),
                'transport': format_currency(budget.get('transport', 0.0)),
                'transport_raw': float(budget.get('transport', 0.0)),
                'dependents': str(budget.get('dependents', 0)),
                'dependents_raw': int(budget.get('dependents', 0)),
                'miscellaneous': format_currency(budget.get('miscellaneous', 0.0)),
                'miscellaneous_raw': float(budget.get('miscellaneous', 0.0)),
                'others': format_currency(budget.get('others', 0.0)),
                'others_raw': float(budget.get('others', 0.0)),
                'custom_categories': budget.get('custom_categories', []),
                'created_at': budget.get('created_at').strftime('%Y-%m-%d') if budget.get('created_at') else 'N/A'
            }
            budgets_dict[budget_data['id']] = budget_data
            if not latest_budget or (budget.get('created_at') and (latest_budget['created_at'] == 'N/A' or budget.get('created_at') > datetime.strptime(latest_budget['created_at'], '%Y-%m-%d'))):
                latest_budget = budget_data

        if not latest_budget:
            latest_budget = {
                'id': None,
                'user_id': None,
                'session_id': session.get('sid', 'unknown'),
                'user_email': current_user.email,
                'income': format_currency(0.0),
                'income_raw': 0.0,
                'fixed_expenses': format_currency(0.0),
                'fixed_expenses_raw': 0.0,
                'variable_expenses': format_currency(0.0),
                'variable_expenses_raw': 0.0,
                'total_expenses': format_currency(0.0),
                'total_expenses_raw': 0.0,
                'savings_goal': format_currency(0.0),
                'savings_goal_raw': 0.0,
                'surplus_deficit': 0.0,
                'surplus_deficit_formatted': format_currency(0.0),
                'housing': format_currency(0.0),
                'housing_raw': 0.0,
                'food': format_currency(0.0),
                'food_raw': 0.0,
                'transport': format_currency(0.0),
                'transport_raw': 0.0,
                'dependents': str(0),
                'dependents_raw': 0,
                'miscellaneous': format_currency(0.0),
                'miscellaneous_raw': 0.0,
                'others': format_currency(0.0),
                'others_raw': 0.0,
                'custom_categories': [],
                'created_at': 'N/A'
            }

        categories = {
            trans('budget_housing_rent', default='Housing/Rent'): latest_budget.get('housing_raw', 0.0),
            trans('budget_food', default='Food'): latest_budget.get('food_raw', 0.0),
            trans('budget_transport', default='Transport'): latest_budget.get('transport_raw', 0.0),
            trans('budget_miscellaneous', default='Miscellaneous'): latest_budget.get('miscellaneous_raw', 0.0),
            trans('budget_others', default='Others'): latest_budget.get('others_raw', 0.0)
        }
        for cat in latest_budget.get('custom_categories', []):
            categories[cat['name']] = cat['amount']
        categories = {k: v for k, v in categories.items() if v > 0}

        tips = [
            trans("budget_tip_track_expenses", default='Track your expenses daily to stay within budget.'),
            trans("budget_tip_ajo_savings", default='Contribute to ajo savings for financial discipline.'),
            trans("budget_tip_data_subscriptions", default='Optimize data subscriptions to reduce costs.'),
            trans("budget_tip_plan_dependents", default='Plan for dependents’ expenses in advance.')
        ]

        insights = []
        try:
            income_float = float(latest_budget.get('income_raw', 0.0))
            surplus_deficit_float = float(latest_budget.get('surplus_deficit', 0.0))
            savings_goal_float = float(latest_budget.get('savings_goal_raw', 0.0))
            if income_float > 0:
                if surplus_deficit_float < 0:
                    insights.append(trans("budget_insight_budget_deficit", default='Your expenses exceed your income. Consider reducing costs.'))
                elif surplus_deficit_float > 0:
                    insights.append(trans("budget_insight_budget_surplus", default='You have a surplus. Consider increasing savings.'))
                if savings_goal_float == 0:
                    insights.append(trans("budget_insight_set_savings_goal", default='Set a savings goal to build financial security.'))
                if income_float > 0 and latest_budget.get('housing_raw', 0.0) / income_float > 0.4:
                    insights.append(trans("budget_insight_high_housing", default='Housing costs exceed 40% of income. Consider cost-saving measures.'))
        except (ValueError, TypeError) as e:
            current_app.logger.warning(f"Error parsing budget amounts for insights: {str(e)}", extra={'session_id': session.get('sid', 'unknown')})

        return render_template(
            'budget/dashboard.html',
            budgets=budgets_dict,
            latest_budget=latest_budget,
            categories=categories,
            tips=tips,
            insights=insights,
            activities=activities,
            tool_title=trans('budget_dashboard', default='Budget Dashboard')
        )
    except Exception as e:
        current_app.logger.error(f"Error in budget.dashboard: {str(e)}", extra={'session_id': session.get('sid', 'unknown')})
        flash(trans('budget_dashboard_load_error', default='Error loading budget dashboard.'), 'danger')
        return render_template(
            'budget/dashboard.html',
            budgets={},
            latest_budget={},
            categories={},
            tips=[],
            insights=[],
            activities=[],
            tool_title=trans('budget_dashboard', default='Budget Dashboard')
        )

@budget_bp.route('/manage', methods=['GET', 'POST'])
@custom_login_required
@utils.requires_role(['personal', 'admin'])
@utils.limiter.limit("10 per minute")
def manage():
    """Manage budgets page."""
    if 'sid' not in session:
        session['sid'] = str(uuid.uuid4())
        current_app.logger.debug(f"New session created with sid: {session['sid']}", extra={'session_id': session['sid']})
    session.permanent = False
    session.modified = True
    db = utils.get_mongo_db()

    try:
        log_tool_usage(
            tool_name='budget',
            db=db,
            user_id=current_user.id,
            session_id=session.get('sid', 'unknown'),
            action='manage_view'
        )
    except Exception as e:
        current_app.logger.error(f"Failed to log tool usage: {str(e)}", extra={'session_id': session.get('sid', 'unknown')})
        flash(trans('budget_log_error', default='Error logging budget activity. Please try again.'), 'warning')

    filter_criteria = {} if utils.is_admin() else {'user_id': current_user.id}

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'delete':
            budget_id = request.form.get('budget_id')
            budget = db.budgets.find_one({'_id': ObjectId(budget_id), **filter_criteria})
            if not budget:
                current_app.logger.warning(f"Budget {budget_id} not found for deletion", extra={'session_id': session.get('sid', 'unknown')})
                flash(trans("budget_not_found", default='Budget not found.'), "danger")
                return redirect(url_for('budget.manage'))
            
            if current_user.is_authenticated and not utils.is_admin():
                if not utils.check_ficore_credit_balance(required_amount=1, user_id=current_user.id):
                    current_app.logger.warning(f"Insufficient Ficore Credits for deleting budget {budget_id} by user {current_user.id}", extra={'session_id': session.get('sid', 'unknown')})
                    flash(trans('budget_insufficient_credits', default='Insufficient Ficore Credits to delete a budget. Please purchase more credits.'), 'danger')
                    return redirect(url_for('dashboard.index'))
            
            try:
                with db.client.start_session() as mongo_session:
                    with mongo_session.start_transaction():
                        result = db.budgets.delete_one({'_id': ObjectId(budget_id), **filter_criteria}, session=mongo_session)
                        if result.deleted_count > 0:
                            if current_user.is_authenticated and not utils.is_admin():
                                if not deduct_ficore_credits(db, current_user.id, 1, 'delete_budget', budget_id):
                                    current_app.logger.error(f"Failed to deduct Ficore Credit for deleting budget {budget_id} by user {current_user.id}", extra={'session_id': session.get('sid', 'unknown')})
                                    flash(trans('budget_credit_deduction_failed', default='Failed to deduct Ficore Credit for deleting budget.'), 'danger')
                                    return redirect(url_for('budget.manage'))
                            mongo_session.commit_transaction()
                        else:
                            current_app.logger.warning(f"Budget ID {budget_id} not found for session {session['sid']}", extra={'session_id': session['sid']})
                            flash(trans("budget_not_found", default='Budget not found.'), "danger")
                            return redirect(url_for('budget.manage'))
                try:
                    caching_ext = current_app.extensions.get('caching')
                    if caching_ext:
                        cache = list(caching_ext.values())[0]
                        cache.delete_memoized(utils.get_budgets)
                        current_app.logger.debug(f"Cleared cache for get_budgets", extra={'session_id': session.get('sid', 'unknown')})
                    else:
                        current_app.logger.warning(f"Caching extension not found; skipping cache clear", extra={'session_id': session.get('sid', 'unknown')})
                except Exception as e:
                    current_app.logger.warning(f"Failed to clear cache for get_budgets: {str(e)}", extra={'session_id': session.get('sid', 'unknown')})
                current_app.logger.info(f"Deleted budget ID {budget_id} for session {session['sid']}", extra={'session_id': session['sid']})
                flash(trans("budget_deleted_success", default='Budget deleted successfully!'), "success")
            except Exception as e:
                current_app.logger.error(f"Failed to delete budget ID {budget_id} for session {session['sid']}: {str(e)}", extra={'session_id': session['sid']})
                flash(trans("budget_delete_failed", default='Error deleting budget.'), "danger")
            return redirect(url_for('budget.manage'))
        
        elif action == 'duplicate':
            budget_id = request.form.get('budget_id')
            original_budget = db.budgets.find_one({'_id': ObjectId(budget_id), **filter_criteria})
            if not original_budget:
                current_app.logger.warning(f"Budget {budget_id} not found for duplication", extra={'session_id': session.get('sid', 'unknown')})
                flash(trans("budget_not_found", default='Budget not found.'), "danger")
                return redirect(url_for('budget.manage'))
            
            if current_user.is_authenticated and not utils.is_admin():
                if not utils.check_ficore_credit_balance(required_amount=1, user_id=current_user.id):
                    current_app.logger.warning(f"Insufficient Ficore Credits for duplicating budget {budget_id} by user {current_user.id}", extra={'session_id': session.get('sid', 'unknown')})
                    flash(trans('budget_insufficient_credits', default='Insufficient Ficore Credits to duplicate a budget. Please purchase more credits.'), 'danger')
                    return redirect(url_for('dashboard.index'))
            
            try:
                # Create a copy of the budget with new ID and timestamp
                new_budget_id = ObjectId()
                duplicated_budget = original_budget.copy()
                duplicated_budget['_id'] = new_budget_id
                duplicated_budget['created_at'] = datetime.utcnow()
                duplicated_budget['session_id'] = session.get('sid', str(uuid.uuid4()))
                
                # Update budget name to indicate it's a copy
                original_name = duplicated_budget.get('budget_name', '')
                if original_name:
                    duplicated_budget['budget_name'] = f"{original_name} (Copy)"
                else:
                    duplicated_budget['budget_name'] = f"Budget Copy - {datetime.utcnow().strftime('%Y-%m-%d')}"
                
                with db.client.start_session() as mongo_session:
                    with mongo_session.start_transaction():
                        result = db.budgets.insert_one(duplicated_budget, session=mongo_session)
                        if current_user.is_authenticated and not utils.is_admin():
                            if not deduct_ficore_credits(db, current_user.id, 1, 'duplicate_budget', new_budget_id):
                                db.budgets.delete_one({'_id': new_budget_id}, session=mongo_session)
                                raise ValueError("Credit deduction failed")
                        mongo_session.commit_transaction()
                
                try:
                    caching_ext = current_app.extensions.get('caching')
                    if caching_ext:
                        cache = list(caching_ext.values())[0]
                        cache.delete_memoized(utils.get_budgets)
                        current_app.logger.debug(f"Cleared cache for get_budgets", extra={'session_id': session.get('sid', 'unknown')})
                    else:
                        current_app.logger.warning(f"Caching extension not found; skipping cache clear", extra={'session_id': session.get('sid', 'unknown')})
                except Exception as e:
                    current_app.logger.warning(f"Failed to clear cache for get_budgets: {str(e)}", extra={'session_id': session.get('sid', 'unknown')})
                
                current_app.logger.info(f"Duplicated budget {budget_id} to {new_budget_id} for session {session['sid']}", extra={'session_id': session['sid']})
                flash(trans("budget_duplicated_success", default='Budget duplicated successfully!'), "success")
            except Exception as e:
                current_app.logger.error(f"Failed to duplicate budget ID {budget_id} for session {session['sid']}: {str(e)}", extra={'session_id': session['sid']})
                flash(trans("budget_duplicate_failed", default='Error duplicating budget.'), "danger")
            return redirect(url_for('budget.manage'))

    try:
        budgets = list(db.budgets.find(filter_criteria).sort('created_at', -1).limit(20))
        budgets_dict = {}
        
        for budget in budgets:
            fixed_raw = float(budget.get('fixed_expenses', 0.0))
            var_raw = float(budget.get('variable_expenses', 0.0))
            total_raw = fixed_raw + var_raw
            budget_data = {
                'id': str(budget['_id']),
                'user_id': budget.get('user_id'),
                'session_id': budget.get('session_id'),
                'user_email': budget.get('user_email', current_user.email),
                'budget_name': budget.get('budget_name'),
                'income': format_currency(budget.get('income', 0.0)),
                'income_raw': float(budget.get('income', 0.0)),
                'total_income': format_currency(budget.get('total_income', budget.get('income', 0.0))),
                'total_income_raw': float(budget.get('total_income', budget.get('income', 0.0))),
                'fixed_expenses': format_currency(fixed_raw),
                'fixed_expenses_raw': fixed_raw,
                'variable_expenses': format_currency(var_raw),
                'variable_expenses_raw': var_raw,
                'total_expenses': format_currency(budget.get('total_expenses', total_raw)),
                'total_expenses_raw': float(budget.get('total_expenses', total_raw)),
                'total_investments': format_currency(budget.get('total_investments', 0.0)),
                'total_investments_raw': float(budget.get('total_investments', 0.0)),
                'savings_goal': format_currency(budget.get('savings_goal', 0.0)),
                'savings_goal_raw': float(budget.get('savings_goal', 0.0)),
                'total_savings': format_currency(budget.get('total_savings', budget.get('savings_goal', 0.0))),
                'total_savings_raw': float(budget.get('total_savings', budget.get('savings_goal', 0.0))),
                'surplus_deficit': float(budget.get('surplus_deficit', 0.0)),
                'surplus_deficit_formatted': format_currency(budget.get('surplus_deficit', 0.0)),
                'income_items': budget.get('income_items', []),
                'expense_items': budget.get('expense_items', []),
                'investment_items': budget.get('investment_items', []),
                'savings_items': budget.get('savings_items', []),
                'housing': format_currency(budget.get('housing', 0.0)),
                'housing_raw': float(budget.get('housing', 0.0)),
                'food': format_currency(budget.get('food', 0.0)),
                'food_raw': float(budget.get('food', 0.0)),
                'transport': format_currency(budget.get('transport', 0.0)),
                'transport_raw': float(budget.get('transport', 0.0)),
                'dependents': str(budget.get('dependents', 0)),
                'dependents_raw': int(budget.get('dependents', 0)),
                'miscellaneous': format_currency(budget.get('miscellaneous', 0.0)),
                'miscellaneous_raw': float(budget.get('miscellaneous', 0.0)),
                'others': format_currency(budget.get('others', 0.0)),
                'others_raw': float(budget.get('others', 0.0)),
                'custom_categories': budget.get('custom_categories', []),
                'created_at': budget.get('created_at').strftime('%Y-%m-%d %H:%M') if budget.get('created_at') else 'N/A'
            }
            budgets_dict[budget_data['id']] = budget_data

        return render_template(
            'budget/manage.html',
            budgets=budgets_dict,
            tool_title=trans('budget_manage_budgets', default='Manage Budgets')
        )
    except Exception as e:
        current_app.logger.error(f"Error in budget.manage: {str(e)}", extra={'session_id': session.get('sid', 'unknown')})
        flash(trans('budget_manage_load_error', default='Error loading budgets for management.'), 'danger')
        return render_template(
            'budget/manage.html',
            budgets={},
            tool_title=trans('budget_manage_budgets', default='Manage Budgets')
        )

@budget_bp.route('/summary')
@login_required
@utils.requires_role(['personal', 'admin'])
@utils.limiter.limit("5 per minute")
def summary():
    db = utils.get_mongo_db()
    try:
        log_tool_usage(
            tool_name='budget',
            db=db,
            user_id=current_user.id,
            session_id=session.get('sid', 'unknown'),
            action='summary_view'
        )
        filter_criteria = {} if utils.is_admin() else {'user_id': current_user.id}
        latest_budget = db.budgets.find_one(filter_criteria, sort=[('created_at', -1)])
        if not latest_budget:
            current_app.logger.info(f"No budget found for user {current_user.id}", extra={'session_id': session.get('sid', 'unknown')})
            return jsonify({
                'totalBudget': format_currency(0.0),
                'user_email': current_user.email
            })
        total_budget = float(latest_budget.get('income', 0.0))
        current_app.logger.info(f"Fetched budget summary for user {current_user.id}: {total_budget}", extra={'session_id': session.get('sid', 'unknown')})
        return jsonify({
            'totalBudget': format_currency(total_budget),
            'user_email': latest_budget.get('user_email', current_user.email if current_user.is_authenticated else '')
        })
    except Exception as e:
        current_app.logger.error(f"Error in budget.summary: {str(e)}", extra={'session_id': session.get('sid', 'unknown')})
        return jsonify({
            'totalBudget': format_currency(0.0),
            'user_email': current_user.email if current_user.is_authenticated else ''
        }), 500

@budget_bp.route('/export_pdf', methods=['GET'])
@custom_login_required
@utils.requires_role(['personal', 'admin'])
def export_pdf():
    """Export budget to PDF with FC deduction, supporting single budget or full history."""
    if 'sid' not in session:
        session['sid'] = str(uuid.uuid4())
    
    db = utils.get_mongo_db()
    budget_id = request.args.get('budget_id')
    
    try:
        # Determine export type and credit cost
        is_single_budget = bool(budget_id)
        credit_cost = 1 if is_single_budget else 2
        export_type = 'single_budget' if is_single_budget else 'full_history'
        
        # Check FC balance before generating PDF
        if current_user.is_authenticated and not utils.is_admin():
            if not utils.check_ficore_credit_balance(required_amount=credit_cost, user_id=current_user.id):
                flash(trans('budget_insufficient_credits_pdf', default=f'Insufficient credits for PDF export. {export_type.replace("_", " ").title()} export costs {credit_cost} FC.'), 'danger')
                return redirect(url_for('budget.manage'))
        
        filter_criteria = {} if utils.is_admin() else {'user_id': str(current_user.id)}
        
        # Fetch budget(s)
        if is_single_budget:
            if not ObjectId.is_valid(budget_id):
                flash(trans('budget_invalid_id', default='Invalid budget ID.'), 'danger')
                return redirect(url_for('budget.manage'))
            budget = db.budgets.find_one({'_id': ObjectId(budget_id), **filter_criteria})
            if not budget:
                flash(trans('budget_no_data_for_pdf', default='No budget data found for PDF export.'), 'warning')
                return redirect(url_for('budget.manage'))
            budgets = [budget]
            report_title = f"Budget Report - {utils.format_date(budget.get('created_at'))}"
            filename = f"budget_report_{budget_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
        else:
            budgets = list(db.budgets.find(filter_criteria).sort('created_at', -1).limit(10))
            if not budgets:
                flash(trans('budget_no_data_for_pdf', default='No budget data found for PDF export.'), 'warning')
                return redirect(url_for('budget.manage'))
            report_title = "Budget History Report"
            filename = f"budget_history_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
        
        # Generate PDF
        buffer = BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        
        # Draw header
        draw_ficore_pdf_header(p, current_user, y_start=height - 50)
        
        # Title
        p.setFont("Helvetica-Bold", 16)
        p.drawString(50, height - 120, report_title)
        
        # Report details
        p.setFont("Helvetica", 12)
        y = height - 150
        p.drawString(50, y, f"Generated: {utils.format_date(datetime.utcnow())}")
        p.drawString(50, y - 20, f"Total Budget Records: {len(budgets)}")
        y -= 60
        
        if is_single_budget:
            # Single budget detailed view
            budget = budgets[0]
            p.setFont("Helvetica-Bold", 12)
            p.drawString(50, y, "Budget Details")
            y -= 20
            p.setFont("Helvetica", 10)
            p.drawString(50, y, f"Date: {utils.format_date(budget.get('created_at'))}")
            p.drawString(50, y - 15, f"Income: {format_currency(budget.get('income', 0))}")
            p.drawString(50, y - 30, f"Fixed Expenses: {format_currency(budget.get('fixed_expenses', 0))}")
            p.drawString(50, y - 45, f"Variable Expenses: {format_currency(budget.get('variable_expenses', 0))}")
            p.drawString(50, y - 60, f"Total Expenses: {format_currency(float(budget.get('fixed_expenses', 0)) + float(budget.get('variable_expenses', 0)))}")
            p.drawString(50, y - 75, f"Savings Goal: {format_currency(budget.get('savings_goal', 0))}")
            p.drawString(50, y - 90, f"Surplus/Deficit: {format_currency(budget.get('surplus_deficit', 0))}")
            p.drawString(50, y - 105, f"Dependents: {budget.get('dependents', 0)}")
            y -= 125
            
            # Categories
            p.setFont("Helvetica-Bold", 10)
            p.drawString(50, y, "Expense Categories")
            y -= 15
            p.setFont("Helvetica", 9)
            p.drawString(50, y, f"Housing: {format_currency(budget.get('housing', 0))}")
            p.drawString(50, y - 15, f"Food: {format_currency(budget.get('food', 0))}")
            p.drawString(50, y - 30, f"Transport: {format_currency(budget.get('transport', 0))}")
            p.drawString(50, y - 45, f"Miscellaneous: {format_currency(budget.get('miscellaneous', 0))}")
            p.drawString(50, y - 60, f"Others: {format_currency(budget.get('others', 0))}")
            y -= 75
            
            # Custom Categories
            if budget.get('custom_categories', []):
                p.setFont("Helvetica-Bold", 10)
                p.drawString(50, y, "Custom Categories")
                y -= 15
                p.setFont("Helvetica", 9)
                for cat in budget.get('custom_categories', []):
                    if y < 50:
                        p.showPage()
                        draw_ficore_pdf_header(p, current_user, y_start=height - 50)
                        y = height - 50
                        p.setFont("Helvetica", 9)
                    p.drawString(50, y, f"{cat['name']}: {format_currency(cat['amount'])}")
                    y -= 15
        else:
            # Budget history table
            p.setFont("Helvetica-Bold", 10)
            p.drawString(50, y, "Date")
            p.drawString(150, y, "Income")
            p.drawString(220, y, "Fixed Exp.")
            p.drawString(290, y, "Variable Exp.")
            p.drawString(370, y, "Savings Goal")
            p.drawString(450, y, "Surplus/Deficit")
            y -= 20
            
            # Budget records
            p.setFont("Helvetica", 9)
            for budget in budgets:
                if y < 50:  # New page if needed
                    p.showPage()
                    draw_ficore_pdf_header(p, current_user, y_start=height - 50)
                    y = height - 120
                    # Redraw header
                    p.setFont("Helvetica-Bold", 10)
                    p.drawString(50, y, "Date")
                    p.drawString(150, y, "Income")
                    p.drawString(220, y, "Fixed Exp.")
                    p.drawString(290, y, "Variable Exp.")
                    p.drawString(370, y, "Savings Goal")
                    p.drawString(450, y, "Surplus/Deficit")
                    y -= 20
                    p.setFont("Helvetica", 9)
                
                p.drawString(50, y, utils.format_date(budget.get('created_at')))
                p.drawString(150, y, format_currency(budget.get('income', 0)))
                p.drawString(220, y, format_currency(budget.get('fixed_expenses', 0)))
                p.drawString(290, y, format_currency(budget.get('variable_expenses', 0)))
                p.drawString(370, y, format_currency(budget.get('savings_goal', 0)))
                p.drawString(450, y, format_currency(budget.get('surplus_deficit', 0)))
                y -= 15
        
        p.save()
        buffer.seek(0)
        
        # Deduct FC for PDF export
        if current_user.is_authenticated and not utils.is_admin():
            if not deduct_ficore_credits(db, current_user.id, credit_cost, f'export_budget_pdf_{export_type}', budget_id if is_single_budget else None):
                flash(trans('budget_credit_deduction_failed', default=f'Failed to deduct credits for {export_type.replace("_", " ").title()} PDF export.'), 'danger')
                return redirect(url_for('budget.manage'))
        
        return Response(
            buffer.getvalue(),
            mimetype='application/pdf',
            headers={'Content-Disposition': f'attachment; filename={filename}'}
        )
        
    except Exception as e:
        logger.error(f"Error exporting {export_type} PDF: {str(e)}", exc_info=True, extra={'session_id': session.get('sid', 'unknown')})
        flash(trans('budget_pdf_error', default='Error generating PDF report.'), 'danger')
        return redirect(url_for('budget.manage'))

@budget_bp.route('/delete_budget', methods=['POST'])
@custom_login_required
@utils.requires_role(['personal', 'admin'])
def delete_budget():
    """Delete a budget record with FC deduction."""
    if 'sid' not in session:
        session['sid'] = str(uuid.uuid4())
    
    db = utils.get_mongo_db()
    
    try:
        data = request.get_json()
        budget_id = data.get('budget_id')
        
        if not ObjectId.is_valid(budget_id):
            return jsonify({'success': False, 'error': trans('budget_invalid_id', default='Invalid budget ID.')}), 400
        
        filter_criteria = {} if utils.is_admin() else {'user_id': str(current_user.id)}
        budget = db.budgets.find_one({'_id': ObjectId(budget_id), **filter_criteria})
        
        if not budget:
            return jsonify({'success': False, 'error': trans('budget_not_found', default='Budget not found.')}), 404
        
        # Delete the budget
        with db.client.start_session() as mongo_session:
            with mongo_session.start_transaction():
                result = db.budgets.delete_one({'_id': ObjectId(budget_id)}, session=mongo_session)
                
                if result.deleted_count > 0:
                    if current_user.is_authenticated and not utils.is_admin():
                        if not deduct_ficore_credits(db, current_user.id, 1, 'delete_budget', budget_id):
                            logger.warning(f"Failed to deduct FC for deleting budget {budget_id} by user {current_user.id}", extra={'session_id': session.get('sid', 'unknown')})
                            # Continue with deletion even if credit deduction fails
                    mongo_session.commit_transaction()
                
                else:
                    return jsonify({'success': False, 'error': trans('budget_delete_failed', default='Failed to delete budget.')}), 500
            
        utils.cache.delete_memoized(utils.get_budgets)
        try:
            log_tool_usage(
                tool_name='budget',
                db=db,
                user_id=current_user.id,
                session_id=session.get('sid', 'no-session'),
                action='delete_budget'
            )
        except Exception as e:
            logger.warning(f"Error logging delete activity: {str(e)}", extra={'session_id': session.get('sid', 'unknown')})
        
        return jsonify({'success': True, 'message': trans('budget_deleted', default='Budget deleted successfully!')})
        
    except Exception as e:
        logger.error(f"Error deleting budget: {str(e)}", exc_info=True, extra={'session_id': session.get('sid', 'unknown')})
        return jsonify({'success': False, 'error': trans('budget_delete_error', default='Error deleting budget.')}), 500
