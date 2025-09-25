from flask import Blueprint, render_template, redirect, url_for, flash, jsonify, session, request
from flask_login import login_required, current_user
from translations import trans
import utils
from bson import ObjectId
from datetime import datetime, timedelta
import logging
from utils import logger
from models import get_recent_transactions, get_transaction_summary

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

@dashboard_bp.route('/')
@login_required
def index():
    """Display the user's dashboard with personal finance summary and real-time data."""
    try:
        db = utils.get_mongo_db()
        
        # Determine query based on user role
        query = {} if utils.is_admin() else {'user_id': str(current_user.id)}
        user_id = str(current_user.id) if not utils.is_admin() else None

        # Initialize data container
        personal_finance_summary = {}
        dashboard_data = {}

        # Fetch personal finance data for personal users and admins
        if current_user.role in ['personal', 'admin']:
            try:
                # Get latest records from each personal finance tool
                latest_budget = db.budgets.find_one(query, sort=[('created_at', -1)])
                latest_bill = db.bills.find_one(query, sort=[('created_at', -1)])
                latest_shopping_list = db.shopping_lists.find_one(query, sort=[('created_at', -1)])

                # Count total records
                total_budgets = db.budgets.count_documents(query)
                total_bills = db.bills.count_documents(query)
                overdue_bills = db.bills.count_documents({**query, 'status': 'overdue'})
                pending_bills = db.bills.count_documents({**query, 'status': 'pending'})
                total_shopping_lists = db.shopping_lists.count_documents(query)

                # Calculate total shopping spent and budget
                shopping_lists = db.shopping_lists.find(query)
                total_shopping_spent = sum(
                    float(item.get('total_amount', 0)) for item in shopping_lists
                    if item.get('total_amount') is not None
                )
                total_shopping_budget = sum(
                    float(item.get('budget', 0)) for item in db.shopping_lists.find(query)
                    if item.get('budget') is not None
                )

                # Get recent transactions (last 10)
                recent_transactions = []
                if user_id:
                    recent_transactions = get_recent_transactions(db, user_id, limit=10)
                elif utils.is_admin():
                    # For admin, get recent transactions from all users
                    recent_transactions = get_recent_transactions(db, None, limit=10) if utils.is_admin() else []

                # Get transaction summary for current month
                current_month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                next_month_start = (current_month_start + timedelta(days=32)).replace(day=1)
                
                transaction_summary = {}
                if user_id:
                    transaction_summary = get_transaction_summary(db, user_id, current_month_start, next_month_start)
                elif utils.is_admin():
                    # For admin, get summary for all users
                    transaction_summary = get_transaction_summary(db, None, current_month_start, next_month_start)

                # Calculate budget progress
                budget_progress = {}
                if latest_budget:
                    total_income = latest_budget.get('total_income', 0)
                    total_expenses = latest_budget.get('total_expenses', 0)
                    actual_expenses = transaction_summary.get('total_expenses', 0)
                    
                    budget_progress = {
                        'planned_income': total_income,
                        'planned_expenses': total_expenses,
                        'actual_income': transaction_summary.get('total_income', 0),
                        'actual_expenses': actual_expenses,
                        'expense_percentage': (actual_expenses / total_expenses * 100) if total_expenses > 0 else 0,
                        'remaining_budget': total_income - actual_expenses,
                        'is_over_budget': actual_expenses > total_expenses
                    }

                personal_finance_summary = {
                    'latest_budget': latest_budget,
                    'latest_bill': latest_bill,
                    'total_budgets': total_budgets,
                    'total_bills': total_bills,
                    'overdue_bills': overdue_bills,
                    'pending_bills': pending_bills,
                    'latest_shopping_list': latest_shopping_list,
                    'total_shopping_lists': total_shopping_lists,
                    'total_shopping_spent': total_shopping_spent,
                    'total_shopping_budget': total_shopping_budget,
                    'has_personal_data': any([latest_budget, latest_bill, latest_shopping_list, total_shopping_lists > 0])
                }

                dashboard_data = {
                    'recent_transactions': recent_transactions,
                    'transaction_summary': transaction_summary,
                    'budget_progress': budget_progress,
                    'upcoming_bills': list(db.bills.find({**query, 'status': 'pending'}).sort('due_date', 1).limit(5))
                }

            except Exception as e:
                logger.error(f"Error fetching personal finance data for user {current_user.id}: {str(e)}")
                personal_finance_summary = {
                    'has_personal_data': False,
                    'total_shopping_lists': 0,
                    'total_shopping_spent': 0.0,
                    'total_shopping_budget': 0.0
                }
                dashboard_data = {
                    'recent_transactions': [],
                    'transaction_summary': {},
                    'budget_progress': {},
                    'upcoming_bills': []
                }

        return render_template(
            'dashboard/index.html',
            personal_finance_summary=personal_finance_summary,
            dashboard_data=dashboard_data
        )
    except Exception as e:
        logger.error(f"Error fetching dashboard data for user {current_user.id}: {str(e)}")
        flash(trans('dashboard_load_error', default='An error occurred while loading the dashboard'), 'danger')
        return redirect(url_for('general_bp.home'))

@dashboard_bp.route('/api/recent-activity')
@login_required
def api_recent_activity():
    """API endpoint to get recent activity data for the dashboard."""
    try:
        db = utils.get_mongo_db()
        user_id = str(current_user.id) if not utils.is_admin() else None
        
        # Debug: Check if transactions collection exists and has data
        transaction_count = db.transactions.count_documents({} if utils.is_admin() else {'user_id': user_id})
        logger.info(f"Total transactions in database: {transaction_count} for user {user_id}")
        
        # Get recent transactions
        recent_transactions = []
        if user_id:
            recent_transactions = get_recent_transactions(db, user_id, limit=3)
        elif utils.is_admin():
            recent_transactions = get_recent_transactions(db, None, limit=3)
        
        logger.info(f"Found {len(recent_transactions)} recent transactions for user {user_id}")
        
        # Format transactions for display
        formatted_transactions = []
        for transaction in recent_transactions:
            formatted_transactions.append({
                'id': str(transaction['_id']),
                'type': transaction['type'],
                'category': transaction['category'],
                'amount': transaction['amount'],
                'description': transaction['description'],
                'timestamp': transaction['timestamp'].isoformat(),
                'status': transaction['status'],
                'formatted_amount': utils.format_currency(transaction['amount']),
                'formatted_date': utils.format_date(transaction['timestamp'])
            })
        
        return jsonify({
            'success': True,
            'recent_transactions': formatted_transactions,
            'debug_info': {
                'total_transactions': transaction_count,
                'user_id': user_id,
                'is_admin': utils.is_admin()
            }
        })
    except Exception as e:
        logger.error(f"Error fetching recent activity: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Failed to fetch recent activity',
            'debug_error': str(e)
        }), 500

@dashboard_bp.route('/api/create-test-transaction', methods=['POST'])
@login_required
def create_test_transaction():
    """Create a test transaction for debugging purposes."""
    try:
        from helpers.transaction_helpers import create_manual_transaction
        
        db = utils.get_mongo_db()
        user_id = current_user.id
        
        transaction_id = create_manual_transaction(
            db=db,
            user_id=user_id,
            transaction_type='expense',
            category='Test',
            amount=100.0,
            description='Test transaction for debugging',
            session_id=session.get('sid', 'test-session'),
            metadata={'source': 'debug_endpoint'}
        )
        
        if transaction_id:
            return jsonify({
                'success': True,
                'transaction_id': transaction_id,
                'message': 'Test transaction created successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to create test transaction'
            }), 500
            
    except Exception as e:
        logger.error(f"Error creating test transaction: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@dashboard_bp.route('/api/manual-transaction', methods=['POST'])
@login_required
def create_manual_transaction_api():
    """API endpoint to create manual transactions."""
    try:
        from helpers.transaction_helpers import create_manual_transaction
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        required_fields = ['type', 'category', 'amount', 'description']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400
        
        db = utils.get_mongo_db()
        user_id = current_user.id
        
        transaction_id = create_manual_transaction(
            db=db,
            user_id=user_id,
            transaction_type=data['type'],
            category=data['category'],
            amount=float(data['amount']),
            description=data['description'],
            session_id=session.get('sid', 'manual-transaction'),
            metadata=data.get('metadata', {})
        )
        
        if transaction_id:
            return jsonify({
                'success': True,
                'transaction_id': transaction_id,
                'message': 'Transaction created successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to create transaction'
            }), 500
            
    except Exception as e:
        logger.error(f"Error creating manual transaction: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
