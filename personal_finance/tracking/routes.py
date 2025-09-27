from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, SelectField, TextAreaField, DateField, SubmitField
from wtforms.validators import DataRequired, NumberRange
from translations import trans
from utils import get_mongo_db, logger
from models import create_transaction, get_transactions
from datetime import datetime

tracking_bp = Blueprint('tracking', __name__, url_prefix='/tracking')

class TransactionForm(FlaskForm):
    type = SelectField(
        trans('tracking_type', default='Transaction Type'),
        choices=[('income', trans('tracking_income', default='Income')), ('expense', trans('tracking_expense', default='Expense'))],
        validators=[DataRequired()]
    )
    category = SelectField(
        trans('tracking_category', default='Category'),
        choices=[
            ('Salary', trans('tracking_salary', default='Salary')),
            ('Freelance', trans('tracking_freelance', default='Freelance')),
            ('Gift', trans('tracking_gift', default='Gift')),
            ('Food', trans('tracking_food', default='Food')),
            ('Utilities', trans('tracking_utilities', default='Utilities')),
            ('Transport', trans('tracking_transport', default='Transport')),
            ('Entertainment', trans('tracking_entertainment', default='Entertainment')),
            ('Other', trans('tracking_other', default='Other'))
        ],
        validators=[DataRequired()]
    )
    amount = FloatField(
        trans('tracking_amount', default='Amount'),
        validators=[DataRequired(), NumberRange(min=0.01, message=trans('tracking_amount_invalid', default='Amount must be positive'))]
    )
    description = TextAreaField(
        trans('tracking_description', default='Description'),
        validators=[DataRequired()]
    )
    transaction_date = DateField(
        trans('tracking_date', default='Date'),
        validators=[DataRequired()],
        default=datetime.utcnow
    )
    submit = SubmitField(trans('tracking_submit', default='Log Transaction'))

@tracking_bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    """Display the transaction logging page."""
    form = TransactionForm()
    try:
        if form.validate_on_submit():
            db = get_mongo_db()
            transaction_data = {
                'user_id': str(current_user.id),
                'type': form.type.data,
                'category': form.category.data,
                'amount': float(form.amount.data),
                'description': form.description.data,
                'timestamp': form.transaction_date.data,
                'status': 'completed',
                'created_at': datetime.utcnow(),
                'metadata': {'source': 'tracking_manual'}
            }
            transaction_id = create_transaction(
                db=db,
                user_id=str(current_user.id),
                transaction_type=form.type.data,
                category=form.category.data,
                amount=float(form.amount.data),
                description=form.description.data,
                session_id=session.get('sid', 'tracking-session'),
                metadata={'source': 'tracking_manual'}
            )
            if transaction_id:
                flash(trans('tracking_transaction_created', default='Transaction logged successfully'), 'success')
                return redirect(url_for('tracking.index'))
            else:
                flash(trans('tracking_transaction_error', default='Failed to log transaction'), 'danger')
    except Exception as e:
        logger.error(f"Error logging transaction for user {current_user.id}: {str(e)}", exc_info=True)
        flash(trans('tracking_transaction_error', default='An error occurred while logging the transaction'), 'danger')
    
    return render_template(
        'tracking/index.html',
        form=form,
        title=trans('tracking_title', default='Log Transaction', lang=session.get('lang', 'en'))
    )

@tracking_bp.route('/history/<transaction_type>')
@login_required
def history(transaction_type):
    """Display transaction history for income or expense."""
    if transaction_type not in ['income', 'expense']:
        flash(trans('tracking_invalid_type', default='Invalid transaction type'), 'danger')
        return redirect(url_for('tracking.index'))
    
    try:
        db = get_mongo_db()
        query = {'user_id': str(current_user.id), 'type': transaction_type, 'status': 'completed'}
        transactions = get_transactions(db, query, limit=50)
        formatted_transactions = [
            {
                'id': str(t['_id']),
                'category': t['category'],
                'amount': t['amount'],
                'description': t['description'],
                'timestamp': utils.format_date(t['timestamp']),
                'formatted_amount': utils.format_currency(t['amount'])
            } for t in transactions
        ]
        title = trans('tracking_income_history', default='Income History') if transaction_type == 'income' else trans('tracking_expense_history', default='Expense History')
        return render_template(
            'tracking/history.html',
            transactions=formatted_transactions,
            transaction_type=transaction_type,
            title=title,
            lang=session.get('lang', 'en')
        )
    except Exception as e:
        logger.error(f"Error fetching {transaction_type} history for user {current_user.id}: {str(e)}", exc_info=True)
        flash(trans('tracking_history_error', default='An error occurred while loading the transaction history'), 'danger')
        return redirect(url_for('tracking.index'))
