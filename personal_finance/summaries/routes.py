from flask import Blueprint, jsonify, current_app, session, request
from flask_login import current_user, login_required
from datetime import datetime, date
from models import get_budgets, get_bills
from utils import get_mongo_db, trans, requires_role, logger, is_admin, get_recent_activities, get_all_recent_activities
from bson import ObjectId

summaries_bp = Blueprint('summaries', __name__, url_prefix='/summaries')

# --- HELPER FUNCTION ---
def parse_currency(value):
    """Parse a currency string to a float, removing symbols and thousand separators."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        # Remove currency symbol (₦) and commas
        cleaned_value = str(value).replace('₦', '').replace(',', '')
        return float(cleaned_value)
    except (ValueError, TypeError) as e:
        logger.warning(
            f"Currency Format Error {value}: could not convert string to float: {str(e)}",
            extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr}
        )
        return 0.0

# --- HELPER FUNCTION ---
def _get_recent_activities_data(user_id=None, is_admin_user=False, db=None, limit=2):
    """Fetch recent activities across all personal finance tools for a user."""
    if db is None:
        db = get_mongo_db()
    return get_recent_activities(user_id=user_id, is_admin_user=is_admin_user, db=db, session_id=session.get('sid', 'no-session-id'), limit=limit)

# --- HELPER FUNCTION FOR NOTIFICATIONS ---
def _get_notifications_data(user_id, is_admin_user, db):
    """Helper function to fetch recent notifications for a user from bill_reminders collection."""
    query = {} if is_admin_user else {'user_id': str(user_id)}
    notifications = db.bill_reminders.find(query).sort('sent_at', -1).limit(10)
    return [{
        'id': str(n.get('notification_id', ObjectId())),
        'message': n.get('message', 'No message'),
        'message_key': n.get('message_key', 'unknown_notification'),
        'type': n.get('type', 'info'),
        'timestamp': n.get('sent_at', datetime.utcnow()).isoformat(),
        'read': n.get('read_status', False),
        'icon': get_notification_icon(n.get('type', 'info'))
    } for n in notifications]

# --- HELPER FUNCTION FOR NOTIFICATION ICONS ---
def get_notification_icon(notification_type):
    """Map notification types to Bootstrap Icons."""
    icons = {
        'info': 'bi-info-circle',
        'warning': 'bi-exclamation-triangle',
        'error': 'bi-x-circle',
        'success': 'bi-check-circle'
    }
    return icons.get(notification_type, 'bi-info-circle')

@summaries_bp.route('/budget/summary')
@login_required
@requires_role(['personal', 'admin'])
def budget_summary():
    """Fetch the latest budget summary for the authenticated user."""
    try:
        db = get_mongo_db()
        filter_criteria = {} if is_admin() else {'user_id': str(current_user.id)}
        latest_budget = get_budgets(db, filter_criteria)
        if latest_budget:
            latest_budget = latest_budget[0]
            income = parse_currency(latest_budget.get('income', 0.0))
            fixed_expenses = parse_currency(latest_budget.get('fixed_expenses', 0.0))
            variable_expenses = parse_currency(latest_budget.get('variable_expenses', 0.0))
            total_budget = income - (fixed_expenses + variable_expenses)
        else:
            total_budget = 0.0
        logger.info(f"Fetched budget summary for user {current_user.id}: {total_budget}", 
                    extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify({'totalBudget': total_budget}), 200
    except Exception as e:
        logger.error(f"Error fetching budget summary for user {current_user.id}: {str(e)}", 
                     extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify({'totalBudget': 0.0, 'error': trans('budget_summary_error', default='Error fetching budget summary', module='budget')}), 500

@summaries_bp.route('/bill/summary')
@login_required
@requires_role(['personal', 'admin'])
def bill_summary():
    """Fetch the summary of bills for the authenticated user."""
    try:
        db = get_mongo_db()
        today = date.today()
        filter_criteria = {} if is_admin() else {'user_id': str(current_user.id)}
        bills = get_bills(db, filter_criteria)
        
        overdue_amount = 0.0
        pending_amount = 0.0
        unpaid_amount = 0.0
        
        for bill in bills:
            try:
                due_date = bill.get('due_date')
                if isinstance(due_date, str):
                    due_date = datetime.strptime(due_date, '%Y-%m-%d').date()
                amount = parse_currency(bill.get('amount', 0))
                status = bill.get('status', 'unpaid')
                
                if status in ['unpaid', 'pending', 'overdue']:
                    if status == 'unpaid':
                        unpaid_amount += amount
                        if due_date < today:
                            overdue_amount += amount
                        elif due_date >= today:
                            pending_amount += amount
                    elif status == 'pending':
                        pending_amount += amount
                    elif status == 'overdue':
                        overdue_amount += amount
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid bill data for bill {bill.get('_id')}: {str(e)}", 
                              extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
                continue

        logger.info(f"Fetched bill summary for user {current_user.id}: overdue={overdue_amount}, pending={pending_amount}, unpaid={unpaid_amount}", 
                    extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify({
            'overdue_amount': overdue_amount,
            'pending_amount': pending_amount,
            'unpaid_amount': unpaid_amount
        }), 200
    except Exception as e:
        logger.error(f"Error fetching bill summary for user {current_user.id}: {str(e)}", 
                     extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify({
            'overdue_amount': 0.0,
            'pending_amount': 0.0,
            'unpaid_amount': 0.0,
            'error': trans('bill_summary_error', default='Error fetching bill summary', module='budget')
        }), 500

@summaries_bp.route('/shopping/summary')
@login_required
@requires_role(['personal', 'admin'])
def shopping_summary():
    """Fetch the summary of active shopping lists for the authenticated user."""
    try:
        db = get_mongo_db()
        shopping_lists = db.shopping_lists.find({'user_id': str(current_user.id), 'status': 'active'}).sort('updated_at', -1)
        total_budget = 0.0
        total_spent = 0.0
        active_lists = 0
        for shopping_list in shopping_lists:
            try:
                total_budget += parse_currency(shopping_list.get('budget', 0))
                total_spent += parse_currency(shopping_list.get('total_spent', 0))
                active_lists += 1
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid shopping list data for list {shopping_list.get('_id')}: {str(e)}", 
                              extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
                continue
        
        logger.info(f"Fetched shopping summary for user {current_user.id}: budget={total_budget}, spent={total_spent}, active_lists={active_lists}", 
                    extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify({
            'total_shopping_budget': float(total_budget),
            'total_shopping_spent': float(total_spent),
            'active_lists': active_lists
        }), 200
    except Exception as e:
        logger.error(f"Error fetching shopping summary for user {current_user.id}: {str(e)}", 
                     extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify({
            'total_shopping_budget': 0.0,
            'total_shopping_spent': 0.0,
            'active_lists': 0,
            'error': trans('shopping_summary_error', default='Error fetching shopping summary', module='shopping')
        }), 500

@summaries_bp.route('/ficore_balance')
@login_required
@requires_role(['personal', 'admin'])
def ficore_balance():
    """Fetch the Ficore Credits balance for the authenticated user."""
    try:
        db = get_mongo_db()
        user = db.users.find_one({'_id': current_user.id})
        balance = parse_currency(user.get('ficore_credit_balance', 0))
        logger.info(f"Fetched Ficore Credits balance for user {current_user.id}: {balance}", 
                    extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify({'balance': balance}), 200
    except Exception as e:
        logger.error(f"Error fetching Ficore Credits balance for user {current_user.id}: {str(e)}", 
                     extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify({'balance': 0.0, 'error': trans('ficore_balance_error', default='Error fetching Ficore Credits balance', module='general')}), 500

@summaries_bp.route('/recent_activity')
@login_required
@requires_role(['personal', 'admin'])
def recent_activity():
    """Return recent activity across all personal finance tools for the current user."""
    try:
        # Log current_user details for debugging
        logger.info(f"Accessing recent_activity for user_id={current_user.id}, role={getattr(current_user, 'role', 'unknown')}", 
                    extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        activities = _get_recent_activities_data(user_id=current_user.id, is_admin_user=getattr(current_user, 'role', None) == 'admin', limit=2)
        logger.info(f"Fetched {len(activities)} recent activities for user {current_user.id}", 
                    extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify(activities), 200
    except Exception as e:
        logger.error(f"Error in summaries.recent_activity: {str(e)}", 
                     extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify([]), 200  # Return empty array instead of error to avoid client-side issues

@summaries_bp.route('/all_activities')
@login_required
@requires_role(['personal', 'admin'])
def all_activities():
    """Return all recent activities (up to 10) across all personal finance tools for the current user."""
    try:
        # Log current_user details for debugging
        logger.info(f"Accessing all_activities for user_id={current_user.id}, role={getattr(current_user, 'role', 'unknown')}", 
                    extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        activities = _get_recent_activities_data(user_id=current_user.id, is_admin_user=getattr(current_user, 'role', None) == 'admin', limit=10)
        logger.info(f"Fetched {len(activities)} recent activities for user {current_user.id} (all_activities)", 
                    extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify(activities), 200
    except Exception as e:
        logger.error(f"Error in summaries.all_activities: {str(e)}", 
                     extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify([]), 200  # Return empty array instead of error to avoid client-side issues

@summaries_bp.route('/notification_count')
@login_required
@requires_role(['personal', 'admin'])
def notification_count():
    """Return the count of unread notifications for the current user."""
    try:
        db = get_mongo_db()
        query = {} if getattr(current_user, 'role', None) == 'admin' else {'user_id': str(current_user.id), 'read_status': False}
        count = db.bill_reminders.count_documents(query)
        logger.info(f"Fetched notification count {count} for user {current_user.id}", 
                    extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify({'count': count}), 200
    except Exception as e:
        logger.error(f"Error fetching notification count: {str(e)}", 
                     extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify({'count': 0, 'error': trans('general_something_went_wrong', default='Failed to fetch notification count', module='general')}), 500

@summaries_bp.route('/notifications')
@login_required
@requires_role(['personal', 'admin'])
def notifications():
    """Return the list of recent notifications for the current user."""
    try:
        db = get_mongo_db()
        query = {} if getattr(current_user, 'role', None) == 'admin' else {'user_id': str(current_user.id)}
        notifications = list(db.bill_reminders.find(query).sort('sent_at', -1).limit(10))

        # Handle cases where notification_id or sent_at might be missing
        notification_ids = []
        for n in notifications:
            if 'notification_id' in n and not n.get('read_status', False):
                notification_ids.append(n['notification_id'])

        if notification_ids:
            db.bill_reminders.update_many(
                {'notification_id': {'$in': notification_ids}},
                {'$set': {'read_status': True}}
            )

        result = []
        for n in notifications:
            try:
                result.append({
                    'id': str(n.get('notification_id', ObjectId())),
                    'message': n.get('message', 'No message'),
                    'message_key': n.get('message_key', 'unknown_notification'),
                    'type': n.get('type', 'info'),
                    'timestamp': n.get('sent_at', datetime.utcnow()).isoformat(),
                    'read': n.get('read_status', False),
                    'icon': get_notification_icon(n.get('type', 'info'))
                })
            except Exception as e:
                logger.warning(f"Skipping invalid notification: {str(e)}", 
                               extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
                continue

        logger.info(f"Fetched {len(result)} notifications for user {current_user.id}", 
                    extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Error fetching notifications: {str(e)}", 
                     extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify([]), 200  # Return empty array instead of error to avoid client-side issues

@summaries_bp.route('/smart_insights')
@login_required
@requires_role(['personal', 'admin'])
def smart_insights():
    """Generate smart financial insights based on transaction data."""
    try:
        from helpers.transaction_helpers import get_transaction_insights
        from datetime import timedelta
        
        db = get_mongo_db()
        user_id = current_user.id if not is_admin() else None
        
        if not user_id and not is_admin():
            return jsonify({'insights': []}), 200
        
        # Get insights for different time periods
        insights_30_days = get_transaction_insights(db, user_id, days=30) if user_id else {'insights': []}
        insights_7_days = get_transaction_insights(db, user_id, days=7) if user_id else {'insights': []}
        
        # Additional insights based on budget vs actual spending
        budget_insights = []
        if user_id:
            # Get latest budget
            latest_budget = db.budgets.find_one({'user_id': str(user_id)}, sort=[('created_at', -1)])
            if latest_budget:
                # Compare budget with actual spending this month
                current_month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                next_month_start = (current_month_start + timedelta(days=32)).replace(day=1)
                
                monthly_transactions = list(db.transactions.find({
                    'user_id': str(user_id),
                    'timestamp': {'$gte': current_month_start, '$lt': next_month_start},
                    'status': 'completed'
                }))
                
                actual_expenses = sum(t['amount'] for t in monthly_transactions if t['type'] in ['expense', 'bill_payment', 'shopping'])
                planned_expenses = latest_budget.get('total_expenses', 0)
                
                if planned_expenses > 0:
                    variance_percentage = ((actual_expenses - planned_expenses) / planned_expenses) * 100
                    
                    if variance_percentage > 10:
                        budget_insights.append({
                            'type': 'budget_variance',
                            'title': 'Budget Alert',
                            'message': f'You are {variance_percentage:.1f}% over your planned expenses this month',
                            'severity': 'warning',
                            'icon': 'bi-exclamation-triangle',
                            'amount': actual_expenses - planned_expenses
                        })
                    elif variance_percentage < -10:
                        budget_insights.append({
                            'type': 'budget_variance',
                            'title': 'Great Job!',
                            'message': f'You are {abs(variance_percentage):.1f}% under your planned expenses this month',
                            'severity': 'success',
                            'icon': 'bi-check-circle',
                            'amount': planned_expenses - actual_expenses
                        })
        
        # Combine all insights
        all_insights = []
        all_insights.extend(insights_30_days.get('insights', []))
        all_insights.extend(budget_insights)
        
        # Add bill payment reminders
        if user_id:
            upcoming_bills = list(db.bills.find({
                'user_id': str(user_id),
                'status': 'pending',
                'due_date': {'$gte': datetime.now(), '$lte': datetime.now() + timedelta(days=7)}
            }).sort('due_date', 1).limit(3))
            
            if upcoming_bills:
                total_upcoming = sum(bill['amount'] for bill in upcoming_bills)
                all_insights.append({
                    'type': 'upcoming_bills',
                    'title': 'Upcoming Bills',
                    'message': f'You have {len(upcoming_bills)} bills due in the next 7 days',
                    'severity': 'info',
                    'icon': 'bi-calendar-event',
                    'amount': total_upcoming,
                    'count': len(upcoming_bills)
                })
        
        # Limit to top 5 insights
        all_insights = all_insights[:5]
        
        logger.info(f"Generated {len(all_insights)} smart insights for user {current_user.id}", 
                    extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        
        return jsonify({
            'insights': all_insights,
            'summary': {
                'total_insights': len(all_insights),
                'period_analyzed': '30 days',
                'last_updated': datetime.utcnow().isoformat()
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error generating smart insights: {str(e)}", 
                     extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify({'insights': [], 'error': 'Failed to generate insights'}), 500

@summaries_bp.route('/spending_analysis')
@login_required
@requires_role(['personal', 'admin'])
def spending_analysis():
    """Provide detailed spending analysis by category and time period."""
    try:
        from datetime import timedelta
        
        db = get_mongo_db()
        user_id = current_user.id if not is_admin() else None
        
        if not user_id and not is_admin():
            return jsonify({'analysis': {}}), 200
        
        # Get spending data for current and previous month
        current_month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        prev_month_start = (current_month_start - timedelta(days=1)).replace(day=1)
        next_month_start = (current_month_start + timedelta(days=32)).replace(day=1)
        
        # Current month transactions
        current_transactions = list(db.transactions.find({
            'user_id': str(user_id),
            'timestamp': {'$gte': current_month_start, '$lt': next_month_start},
            'type': {'$in': ['expense', 'bill_payment', 'shopping']},
            'status': 'completed'
        }))
        
        # Previous month transactions
        prev_transactions = list(db.transactions.find({
            'user_id': str(user_id),
            'timestamp': {'$gte': prev_month_start, '$lt': current_month_start},
            'type': {'$in': ['expense', 'bill_payment', 'shopping']},
            'status': 'completed'
        }))
        
        # Analyze by category
        current_by_category = {}
        prev_by_category = {}
        
        for transaction in current_transactions:
            category = transaction['category']
            current_by_category[category] = current_by_category.get(category, 0) + transaction['amount']
        
        for transaction in prev_transactions:
            category = transaction['category']
            prev_by_category[category] = prev_by_category.get(category, 0) + transaction['amount']
        
        # Calculate changes
        category_analysis = {}
        all_categories = set(current_by_category.keys()) | set(prev_by_category.keys())
        
        for category in all_categories:
            current_amount = current_by_category.get(category, 0)
            prev_amount = prev_by_category.get(category, 0)
            
            if prev_amount > 0:
                change_percentage = ((current_amount - prev_amount) / prev_amount) * 100
            else:
                change_percentage = 100 if current_amount > 0 else 0
            
            category_analysis[category] = {
                'current_amount': current_amount,
                'previous_amount': prev_amount,
                'change_amount': current_amount - prev_amount,
                'change_percentage': change_percentage,
                'trend': 'up' if change_percentage > 5 else 'down' if change_percentage < -5 else 'stable'
            }
        
        # Overall totals
        current_total = sum(current_by_category.values())
        prev_total = sum(prev_by_category.values())
        total_change = ((current_total - prev_total) / prev_total * 100) if prev_total > 0 else 0
        
        analysis = {
            'current_month': {
                'total_spending': current_total,
                'transaction_count': len(current_transactions),
                'by_category': current_by_category
            },
            'previous_month': {
                'total_spending': prev_total,
                'transaction_count': len(prev_transactions),
                'by_category': prev_by_category
            },
            'comparison': {
                'total_change_amount': current_total - prev_total,
                'total_change_percentage': total_change,
                'category_analysis': category_analysis
            },
            'top_categories': sorted(current_by_category.items(), key=lambda x: x[1], reverse=True)[:5]
        }
        
        logger.info(f"Generated spending analysis for user {current_user.id}", 
                    extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        
        return jsonify({'analysis': analysis}), 200
        
    except Exception as e:
        logger.error(f"Error generating spending analysis: {str(e)}", 
                     extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify({'analysis': {}, 'error': 'Failed to generate spending analysis'}), 500
