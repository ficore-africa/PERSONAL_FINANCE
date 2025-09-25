"""
API routes with offline support for FiCore Africa
Handles offline data synchronization and provides offline-friendly responses
"""

from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime, timedelta
import json
from bson import ObjectId

# Create blueprint for offline API routes
offline_api_bp = Blueprint('offline_api', __name__, url_prefix='/api/offline')

@offline_api_bp.route('/sync', methods=['POST'])
@login_required
def sync_offline_data():
    """Sync offline data when user comes back online"""
    try:
        data = request.get_json()
        if not data or 'actions' not in data:
            return jsonify({'error': 'No actions to sync'}), 400
        
        db = current_app.extensions['mongo']['ficodb']
        synced_actions = []
        failed_actions = []
        
        for action in data['actions']:
            try:
                result = process_offline_action(db, action, current_user.id)
                if result['success']:
                    synced_actions.append({
                        'id': action.get('id'),
                        'type': action.get('type'),
                        'result': result
                    })
                else:
                    failed_actions.append({
                        'id': action.get('id'),
                        'error': result.get('error', 'Unknown error')
                    })
            except Exception as e:
                failed_actions.append({
                    'id': action.get('id'),
                    'error': str(e)
                })
        
        return jsonify({
            'success': True,
            'synced': len(synced_actions),
            'failed': len(failed_actions),
            'synced_actions': synced_actions,
            'failed_actions': failed_actions
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def process_offline_action(db, action, user_id):
    """Process a single offline action"""
    action_type = action.get('type')
    action_data = action.get('data', {})
    
    try:
        if action_type == 'save_bill':
            return save_offline_bill(db, action_data, user_id)
        elif action_type == 'save_budget':
            return save_offline_budget(db, action_data, user_id)
        elif action_type == 'save_shopping_item':
            return save_offline_shopping_item(db, action_data, user_id)
        elif action_type == 'form_submission':
            return process_offline_form(db, action, user_id)
        else:
            return {'success': False, 'error': f'Unknown action type: {action_type}'}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def save_offline_bill(db, data, user_id):
    """Save offline bill data"""
    try:
        bill_data = {
            'user_id': user_id,
            'title': data.get('title', ''),
            'amount': float(data.get('amount', 0)),
            'due_date': datetime.fromisoformat(data.get('due_date', datetime.now().isoformat())),
            'category': data.get('category', 'Other'),
            'description': data.get('description', ''),
            'status': data.get('status', 'pending'),
            'created_at': datetime.utcnow(),
            'synced_from_offline': True,
            'offline_timestamp': data.get('_timestamp')
        }
        
        result = db.bills.insert_one(bill_data)
        return {
            'success': True,
            'id': str(result.inserted_id),
            'message': 'Bill saved successfully'
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}

def save_offline_budget(db, data, user_id):
    """Save offline budget data"""
    try:
        budget_data = {
            'user_id': user_id,
            'name': data.get('name', ''),
            'total_amount': float(data.get('total_amount', 0)),
            'categories': data.get('categories', []),
            'period': data.get('period', 'monthly'),
            'start_date': datetime.fromisoformat(data.get('start_date', datetime.now().isoformat())),
            'created_at': datetime.utcnow(),
            'synced_from_offline': True,
            'offline_timestamp': data.get('_timestamp')
        }
        
        result = db.budgets.insert_one(budget_data)
        return {
            'success': True,
            'id': str(result.inserted_id),
            'message': 'Budget saved successfully'
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}

def save_offline_shopping_item(db, data, user_id):
    """Save offline shopping item"""
    try:
        # First, ensure shopping list exists or create one
        list_id = data.get('list_id')
        if not list_id:
            # Create a default list
            list_data = {
                'user_id': user_id,
                'name': 'Offline Shopping List',
                'created_at': datetime.utcnow()
            }
            list_result = db.shopping_lists.insert_one(list_data)
            list_id = str(list_result.inserted_id)
        
        item_data = {
            'user_id': user_id,
            'list_id': list_id,
            'name': data.get('name', ''),
            'quantity': int(data.get('quantity', 1)),
            'price': float(data.get('price', 0)) if data.get('price') else None,
            'category': data.get('category', 'Other'),
            'purchased': data.get('purchased', False),
            'created_at': datetime.utcnow(),
            'synced_from_offline': True,
            'offline_timestamp': data.get('_timestamp')
        }
        
        result = db.shopping_items.insert_one(item_data)
        return {
            'success': True,
            'id': str(result.inserted_id),
            'list_id': list_id,
            'message': 'Shopping item saved successfully'
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}

def process_offline_form(db, action, user_id):
    """Process generic offline form submission"""
    try:
        form_data = json.loads(action.get('body', '{}'))
        form_id = action.get('formId', '')
        url = action.get('url', '')
        
        # Route to appropriate handler based on URL
        if '/bills/' in url:
            return save_offline_bill(db, form_data, user_id)
        elif '/budget/' in url:
            return save_offline_budget(db, form_data, user_id)
        elif '/shopping/' in url:
            return save_offline_shopping_item(db, form_data, user_id)
        else:
            # Generic form storage
            form_submission = {
                'user_id': user_id,
                'form_id': form_id,
                'url': url,
                'data': form_data,
                'submitted_at': datetime.utcnow(),
                'synced_from_offline': True
            }
            
            result = db.offline_form_submissions.insert_one(form_submission)
            return {
                'success': True,
                'id': str(result.inserted_id),
                'message': 'Form submission saved successfully'
            }
    except Exception as e:
        return {'success': False, 'error': str(e)}

@offline_api_bp.route('/cache/<cache_key>', methods=['GET'])
@login_required
def get_cached_data(cache_key):
    """Get cached data for offline use"""
    try:
        db = current_app.extensions['mongo']['ficodb']
        
        # Define cache handlers
        cache_handlers = {
            'dashboard_summary': get_dashboard_summary,
            'recent_bills': get_recent_bills,
            'budget_overview': get_budget_overview,
            'shopping_lists': get_shopping_lists,
            'user_profile': get_user_profile
        }
        
        if cache_key not in cache_handlers:
            return jsonify({'error': 'Invalid cache key'}), 400
        
        data = cache_handlers[cache_key](db, current_user.id)
        
        return jsonify({
            'success': True,
            'data': data,
            'cached_at': datetime.utcnow().isoformat(),
            'cache_key': cache_key
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def get_dashboard_summary(db, user_id):
    """Get dashboard summary data"""
    try:
        # Get recent bills
        recent_bills = list(db.bills.find(
            {'user_id': user_id}
        ).sort('created_at', -1).limit(5))
        
        # Get budget summary
        current_budget = db.budgets.find_one(
            {'user_id': user_id},
            sort=[('created_at', -1)]
        )
        
        # Convert ObjectIds to strings
        for bill in recent_bills:
            bill['_id'] = str(bill['_id'])
            if 'due_date' in bill:
                bill['due_date'] = bill['due_date'].isoformat()
            if 'created_at' in bill:
                bill['created_at'] = bill['created_at'].isoformat()
        
        if current_budget:
            current_budget['_id'] = str(current_budget['_id'])
            if 'created_at' in current_budget:
                current_budget['created_at'] = current_budget['created_at'].isoformat()
            if 'start_date' in current_budget:
                current_budget['start_date'] = current_budget['start_date'].isoformat()
        
        return {
            'recent_bills': recent_bills,
            'current_budget': current_budget,
            'total_bills': db.bills.count_documents({'user_id': user_id}),
            'pending_bills': db.bills.count_documents({'user_id': user_id, 'status': 'pending'})
        }
    except Exception as e:
        return {'error': str(e)}

def get_recent_bills(db, user_id):
    """Get recent bills"""
    try:
        bills = list(db.bills.find(
            {'user_id': user_id}
        ).sort('created_at', -1).limit(10))
        
        for bill in bills:
            bill['_id'] = str(bill['_id'])
            if 'due_date' in bill:
                bill['due_date'] = bill['due_date'].isoformat()
            if 'created_at' in bill:
                bill['created_at'] = bill['created_at'].isoformat()
        
        return bills
    except Exception as e:
        return {'error': str(e)}

def get_budget_overview(db, user_id):
    """Get budget overview"""
    try:
        budgets = list(db.budgets.find(
            {'user_id': user_id}
        ).sort('created_at', -1).limit(5))
        
        for budget in budgets:
            budget['_id'] = str(budget['_id'])
            if 'created_at' in budget:
                budget['created_at'] = budget['created_at'].isoformat()
            if 'start_date' in budget:
                budget['start_date'] = budget['start_date'].isoformat()
        
        return budgets
    except Exception as e:
        return {'error': str(e)}

def get_shopping_lists(db, user_id):
    """Get shopping lists with items"""
    try:
        lists = list(db.shopping_lists.find(
            {'user_id': user_id}
        ).sort('created_at', -1).limit(5))
        
        for shopping_list in lists:
            shopping_list['_id'] = str(shopping_list['_id'])
            if 'created_at' in shopping_list:
                shopping_list['created_at'] = shopping_list['created_at'].isoformat()
            
            # Get items for this list
            items = list(db.shopping_items.find(
                {'list_id': str(shopping_list['_id'])}
            ))
            
            for item in items:
                item['_id'] = str(item['_id'])
                if 'created_at' in item:
                    item['created_at'] = item['created_at'].isoformat()
            
            shopping_list['items'] = items
        
        return lists
    except Exception as e:
        return {'error': str(e)}

def get_user_profile(db, user_id):
    """Get user profile data"""
    try:
        user = db.users.find_one({'_id': user_id})
        if user:
            # Remove sensitive data
            user.pop('password', None)
            user['_id'] = str(user['_id'])
            if 'created_at' in user:
                user['created_at'] = user['created_at'].isoformat()
        
        return user
    except Exception as e:
        return {'error': str(e)}

@offline_api_bp.route('/status', methods=['GET'])
@login_required
def get_offline_status():
    """Get offline sync status"""
    try:
        db = current_app.extensions['mongo']['ficodb']
        
        # Count offline items that need syncing
        offline_bills = db.bills.count_documents({
            'user_id': current_user.id,
            'synced_from_offline': True
        })
        
        offline_budgets = db.budgets.count_documents({
            'user_id': current_user.id,
            'synced_from_offline': True
        })
        
        offline_shopping = db.shopping_items.count_documents({
            'user_id': current_user.id,
            'synced_from_offline': True
        })
        
        return jsonify({
            'success': True,
            'offline_items': {
                'bills': offline_bills,
                'budgets': offline_budgets,
                'shopping_items': offline_shopping,
                'total': offline_bills + offline_budgets + offline_shopping
            },
            'last_sync': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500