"""
Transaction helper functions for automatically creating transaction records
when financial activities occur across different modules.
"""

from datetime import datetime
from models import create_transaction
from utils import logger
from flask import session
from flask_login import current_user


def create_bill_payment_transaction(db, bill_data, session_id=None):
    """
    Create a transaction record when a bill is marked as paid.
    
    Args:
        db: MongoDB database instance
        bill_data: Dictionary containing bill information
        session_id: Optional session ID
    
    Returns:
        str: Transaction ID if successful, None otherwise
    """
    try:
        transaction_data = {
            'user_id': bill_data['user_id'],
            'session_id': session_id or session.get('sid', 'no-session-id'),
            'type': 'bill_payment',
            'category': bill_data.get('category', 'Bills'),
            'subcategory': bill_data.get('bill_name', 'Bill Payment'),
            'amount': float(bill_data['amount']),
            'description': f"Payment for {bill_data.get('bill_name', 'Bill')}",
            'timestamp': datetime.utcnow(),
            'status': 'completed',
            'reference_id': str(bill_data.get('_id', '')),
            'reference_type': 'bill',
            'metadata': {
                'bill_name': bill_data.get('bill_name'),
                'payment_method': 'manual',
                'notes': f"Bill payment recorded automatically"
            },
            'created_at': datetime.utcnow()
        }
        
        transaction_id = create_transaction(db, transaction_data)
        logger.info(f"Created bill payment transaction {transaction_id} for bill {bill_data.get('bill_name')}")
        return transaction_id
        
    except Exception as e:
        logger.error(f"Error creating bill payment transaction: {str(e)}")
        return None


def create_shopping_expense_transaction(db, shopping_item_data, shopping_list_data, session_id=None):
    """
    Create a transaction record when a shopping item is purchased.
    
    Args:
        db: MongoDB database instance
        shopping_item_data: Dictionary containing shopping item information
        shopping_list_data: Dictionary containing shopping list information
        session_id: Optional session ID
    
    Returns:
        str: Transaction ID if successful, None otherwise
    """
    try:
        total_amount = float(shopping_item_data.get('price', 0)) * float(shopping_item_data.get('quantity', 1))
        
        transaction_data = {
            'user_id': shopping_item_data['user_id'],
            'session_id': session_id or session.get('sid', 'no-session-id'),
            'type': 'shopping',
            'category': shopping_item_data.get('category', 'Shopping').title(),
            'subcategory': shopping_item_data.get('name', 'Shopping Item'),
            'amount': total_amount,
            'description': f"Purchase: {shopping_item_data.get('name', 'Shopping Item')} (x{shopping_item_data.get('quantity', 1)})",
            'timestamp': datetime.utcnow(),
            'status': 'completed',
            'reference_id': str(shopping_item_data.get('_id', '')),
            'reference_type': 'shopping_item',
            'metadata': {
                'shopping_list_name': shopping_list_data.get('name'),
                'item_name': shopping_item_data.get('name'),
                'quantity': shopping_item_data.get('quantity'),
                'unit_price': shopping_item_data.get('price'),
                'store': shopping_item_data.get('store'),
                'notes': f"Shopping item purchase recorded automatically"
            },
            'created_at': datetime.utcnow()
        }
        
        transaction_id = create_transaction(db, transaction_data)
        logger.info(f"Created shopping expense transaction {transaction_id} for item {shopping_item_data.get('name')}")
        return transaction_id
        
    except Exception as e:
        logger.error(f"Error creating shopping expense transaction: {str(e)}")
        return None


def create_budget_allocation_transaction(db, budget_data, allocation_type, amount, description, session_id=None):
    """
    Create a transaction record for budget allocations (income, expenses, savings, investments).
    
    Args:
        db: MongoDB database instance
        budget_data: Dictionary containing budget information
        allocation_type: Type of allocation ('income', 'expense', 'savings', 'investment')
        amount: Amount being allocated
        description: Description of the allocation
        session_id: Optional session ID
    
    Returns:
        str: Transaction ID if successful, None otherwise
    """
    try:
        transaction_data = {
            'user_id': budget_data['user_id'],
            'session_id': session_id or session.get('sid', 'no-session-id'),
            'type': 'budget_allocation',
            'category': allocation_type.title(),
            'subcategory': description,
            'amount': float(amount),
            'description': f"Budget allocation: {description}",
            'timestamp': datetime.utcnow(),
            'status': 'completed',
            'reference_id': str(budget_data.get('_id', '')),
            'reference_type': 'budget',
            'metadata': {
                'budget_name': budget_data.get('budget_name'),
                'allocation_type': allocation_type,
                'notes': f"Budget allocation recorded automatically"
            },
            'created_at': datetime.utcnow()
        }
        
        transaction_id = create_transaction(db, transaction_data)
        logger.info(f"Created budget allocation transaction {transaction_id} for {allocation_type}: {description}")
        return transaction_id
        
    except Exception as e:
        logger.error(f"Error creating budget allocation transaction: {str(e)}")
        return None


def create_manual_transaction(db, user_id, transaction_type, category, amount, description, session_id=None, metadata=None):
    """
    Create a manual transaction record.
    
    Args:
        db: MongoDB database instance
        user_id: User ID
        transaction_type: Type of transaction ('income', 'expense', 'transfer', etc.)
        category: Transaction category
        amount: Transaction amount
        description: Transaction description
        session_id: Optional session ID
        metadata: Optional metadata dictionary
    
    Returns:
        str: Transaction ID if successful, None otherwise
    """
    try:
        transaction_data = {
            'user_id': str(user_id),
            'session_id': session_id or session.get('sid', 'no-session-id'),
            'type': transaction_type,
            'category': category,
            'amount': float(amount),
            'description': description,
            'timestamp': datetime.utcnow(),
            'status': 'completed',
            'reference_type': 'manual',
            'metadata': metadata or {},
            'created_at': datetime.utcnow()
        }
        
        transaction_id = create_transaction(db, transaction_data)
        logger.info(f"Created manual transaction {transaction_id}: {description}")
        return transaction_id
        
    except Exception as e:
        logger.error(f"Error creating manual transaction: {str(e)}")
        return None


def update_transaction_status(db, transaction_id, new_status, notes=None):
    """
    Update the status of an existing transaction.
    
    Args:
        db: MongoDB database instance
        transaction_id: Transaction ID to update
        new_status: New status ('completed', 'pending', 'failed', 'cancelled')
        notes: Optional notes about the status change
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        update_data = {
            'status': new_status,
            'updated_at': datetime.utcnow()
        }
        
        if notes:
            update_data['metadata.status_notes'] = notes
        
        result = db.transactions.update_one(
            {'_id': transaction_id},
            {'$set': update_data}
        )
        
        if result.modified_count > 0:
            logger.info(f"Updated transaction {transaction_id} status to {new_status}")
            return True
        else:
            logger.warning(f"No transaction found with ID {transaction_id}")
            return False
            
    except Exception as e:
        logger.error(f"Error updating transaction status: {str(e)}")
        return False


def get_transaction_insights(db, user_id, days=30):
    """
    Generate insights from transaction data for the dashboard.
    
    Args:
        db: MongoDB database instance
        user_id: User ID
        days: Number of days to analyze (default: 30)
    
    Returns:
        dict: Dictionary containing insights
    """
    try:
        from datetime import timedelta
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Get transactions for the period
        transactions = list(db.transactions.find({
            'user_id': str(user_id),
            'timestamp': {'$gte': start_date, '$lte': end_date},
            'status': 'completed'
        }))
        
        if not transactions:
            return {
                'total_transactions': 0,
                'insights': []
            }
        
        insights = []
        
        # Calculate spending by category
        category_spending = {}
        total_expenses = 0
        total_income = 0
        
        for transaction in transactions:
            if transaction['type'] in ['expense', 'bill_payment', 'shopping']:
                category = transaction['category']
                amount = transaction['amount']
                category_spending[category] = category_spending.get(category, 0) + amount
                total_expenses += amount
            elif transaction['type'] == 'income':
                total_income += transaction['amount']
        
        # Find top spending category
        if category_spending:
            top_category = max(category_spending, key=category_spending.get)
            top_amount = category_spending[top_category]
            percentage = (top_amount / total_expenses * 100) if total_expenses > 0 else 0
            
            insights.append({
                'type': 'spending_category',
                'title': f'Top Spending Category',
                'message': f'You spent {percentage:.1f}% of your expenses on {top_category}',
                'amount': top_amount,
                'category': top_category
            })
        
        # Compare with previous period
        prev_start_date = start_date - timedelta(days=days)
        prev_transactions = list(db.transactions.find({
            'user_id': str(user_id),
            'timestamp': {'$gte': prev_start_date, '$lt': start_date},
            'status': 'completed'
        }))
        
        prev_expenses = sum(t['amount'] for t in prev_transactions if t['type'] in ['expense', 'bill_payment', 'shopping'])
        
        if prev_expenses > 0:
            expense_change = ((total_expenses - prev_expenses) / prev_expenses) * 100
            if abs(expense_change) > 5:  # Only show if change is significant
                direction = 'increased' if expense_change > 0 else 'decreased'
                insights.append({
                    'type': 'spending_trend',
                    'title': f'Spending Trend',
                    'message': f'Your spending has {direction} by {abs(expense_change):.1f}% compared to the previous {days} days',
                    'change_percentage': expense_change
                })
        
        # Savings rate insight
        if total_income > 0:
            savings_rate = ((total_income - total_expenses) / total_income) * 100
            insights.append({
                'type': 'savings_rate',
                'title': 'Savings Rate',
                'message': f'You saved {savings_rate:.1f}% of your income this period',
                'percentage': savings_rate,
                'amount': total_income - total_expenses
            })
        
        return {
            'total_transactions': len(transactions),
            'total_income': total_income,
            'total_expenses': total_expenses,
            'insights': insights,
            'category_breakdown': category_spending
        }
        
    except Exception as e:
        logger.error(f"Error generating transaction insights: {str(e)}")
        return {
            'total_transactions': 0,
            'insights': []
        }