# FiCore Africa Personal Finance Management Platform

INTERNAL USE ONLY: This codebase contains proprietary and confidential information belonging to FICORE LABS LIMITED. Unauthorized access, use, copying, or distribution of any part of this codebase is strictly prohibited.

## Overview

FiCore Africa is a comprehensive personal finance management platform built with Flask, designed to help users manage their budgets, bills, shopping lists, and financial transactions. The application supports multiple user roles, multilingual functionality (English and Hausa), and includes both online and offline capabilities.

## Core Features

### 🏠 Dashboard & Analytics
- **Personal Dashboard**: Real-time financial overview with transaction summaries
- **Smart Insights**: AI-powered financial insights and spending analysis
- **Budget Performance Tracking**: Compare planned vs actual spending
- **Recent Activity Feed**: Real-time transaction and activity monitoring
- **Quick Transaction Entry**: Manual income/expense transaction creation

### 💰 Budget Management
- **Comprehensive Budget Planning**: Create detailed budgets with multiple categories
- **Income Tracking**: Multiple income sources with notes
- **Expense Categories**: Detailed expense breakdown (housing, food, transport, etc.)
- **Investment Planning**: Track investment allocations
- **Savings Goals**: Set and monitor savings targets
- **Supports & Dependents**: Track family support, donations, and contributions
- **Real-time Calculations**: Automatic surplus/deficit calculations
- **Budget History**: Track budget performance over time
- **PDF Export**: Generate detailed budget reports

### 📋 Bill Management
- **Bill Tracking**: Comprehensive bill management with due dates
- **Multiple Categories**: Utilities, rent, data/internet, ajo/esusu, food, transport, etc.
- **Payment Status**: Track pending, paid, and overdue bills
- **Recurring Bills**: Support for one-time, weekly, monthly, and quarterly bills
- **Email Reminders**: Automated email notifications for upcoming bills
- **Bill History**: Complete payment history and tracking
- **Bulk Operations**: Mark multiple bills as paid

### 🛒 Shopping Management
- **Shopping Lists**: Create and manage multiple shopping lists
- **Budget Tracking**: Set budgets for shopping lists with spending monitoring
- **Item Management**: Add items with quantity, price, unit, and store information
- **Category Organization**: Organize items by fruits, vegetables, dairy, meat, etc.
- **Collaborative Lists**: Share shopping lists with collaborators
- **Shopping Status**: Track items as "to buy" or "bought"
- **Frequency Planning**: Set purchase frequency for regular items
- **PDF Export**: Generate shopping list reports

### 📊 Reports & Analytics
- **Budget Performance Reports**: Detailed budget vs actual spending analysis
- **Shopping Reports**: Comprehensive shopping history and spending patterns
- **Transaction Reports**: Income and expense tracking with categorization
- **PDF Generation**: Professional reports with branding
- **Date Range Filtering**: Custom report periods
- **Admin Reports**: System-wide analytics for administrators

### 👥 User Management
- **Multi-Role Support**: Personal users and administrators
- **User Authentication**: Secure login with optional 2FA
- **Profile Management**: Complete user profile with photo upload
- **Language Support**: English and Hausa localization
- **Setup Wizard**: Guided onboarding for new users
- **Account Settings**: Notification preferences, language settings

### 💳 Credit System
- **FiCore Credits**: Internal credit system for premium features
- **Credit Requests**: Users can request additional credits
- **Transaction History**: Complete credit usage tracking
- **Admin Approval**: Credit request approval workflow
- **Automatic Allocation**: New users receive signup bonus credits

### 🔧 Admin Features
- **Admin Dashboard**: System statistics and user management
- **User Management**: View, suspend, and manage user accounts
- **Credit Management**: Approve/deny credit requests
- **Data Management**: View and manage all user data (budgets, bills, shopping)
- **Audit Logs**: Complete system activity tracking
- **Feedback Management**: View and manage user feedback
- **System Reports**: Generate customer and usage reports

### 🌐 API & Integration
- **RESTful APIs**: Comprehensive API endpoints for all features
- **Offline Support**: Progressive Web App with offline functionality
- **Service Worker**: Advanced caching strategies for offline use
- **Background Sync**: Automatic data synchronization when online
- **IndexedDB Storage**: Client-side data storage for offline use

### 📱 Progressive Web App (PWA)
- **Offline Functionality**: Full app functionality without internet
- **Service Worker**: Advanced caching and background sync
- **Installable**: Can be installed on mobile devices and desktops
- **Responsive Design**: Optimized for all screen sizes
- **Push Notifications**: Real-time notifications (when supported)

### 🔒 Security Features
- **CSRF Protection**: Cross-site request forgery protection
- **Session Management**: Secure session handling with MongoDB
- **Password Hashing**: Secure password storage with Werkzeug
- **Role-based Access**: Granular permission system
- **Audit Logging**: Complete activity tracking for security

### 🌍 Internationalization
- **Multi-language Support**: English and Hausa
- **Dynamic Translation**: Runtime language switching
- **Localized Content**: All UI elements and messages translated
- **Currency Formatting**: Proper currency display for different locales

## Technical Architecture

### Backend Technologies
- **Flask**: Python web framework
- **MongoDB**: NoSQL database with GridFS for file storage
- **PyMongo**: MongoDB driver with transaction support
- **Flask-Login**: User session management
- **Flask-WTF**: Form handling and CSRF protection
- **Flask-Mail**: Email functionality
- **ReportLab**: PDF generation
- **APScheduler**: Background task scheduling

### Frontend Technologies
- **Bootstrap 5**: Responsive UI framework
- **JavaScript ES6+**: Modern JavaScript features
- **Service Workers**: Offline functionality
- **IndexedDB**: Client-side database
- **Progressive Enhancement**: Works without JavaScript

### Database Schema
- **Users Collection**: User profiles and authentication
- **Budgets Collection**: Budget data with item-based structure
- **Bills Collection**: Bill tracking and payment history
- **Shopping Collections**: Lists and items with collaboration
- **Transactions Collection**: Financial transaction records
- **Credit System**: FiCore credits and transaction history
- **Audit Logs**: System activity and security tracking

### Deployment Features
- **Docker Support**: Containerized deployment
- **Environment Configuration**: Flexible configuration management
- **Health Checks**: Application health monitoring
- **Logging**: Comprehensive logging with session tracking
- **Error Handling**: Graceful error handling and user feedback

## User Roles

### Personal Users
- Create and manage personal budgets
- Track bills and payments
- Manage shopping lists
- View personal reports and analytics
- Request additional credits
- Access all personal finance tools

### Administrators
- Full system access and management
- User account management
- Credit request approval
- System-wide reports and analytics
- Data management and cleanup
- Audit log access

## Key Workflows

### Budget Creation
1. User creates budget with income, expenses, investments, savings, and dependents
2. System calculates surplus/deficit automatically
3. Budget is saved with transaction records
4. Dashboard updates with new budget data
5. Smart insights generated based on budget patterns

### Bill Management
1. User creates bills with due dates and categories
2. System sends email reminders (if enabled)
3. User marks bills as paid
4. Payment transactions are automatically created
5. Bill history and analytics updated

### Shopping Process
1. User creates shopping list with budget
2. Items added with prices and categories
3. Collaborative sharing with other users
4. Items marked as bought create expense transactions
5. Budget tracking shows spending vs planned

### Credit System
1. Users receive signup bonus credits
2. Premium features require credit deduction
3. Users can request additional credits with receipt upload
4. Admins approve/deny requests
5. Credit history tracked for transparency

## Recent Enhancements

### Budget System Improvements
- Added Supports & Dependents category for family support tracking
- Enhanced item-based budget structure with detailed breakdowns
- Improved real-time calculations and form validation
- Better dashboard integration with comprehensive data display

### Dashboard Enhancements
- Smart insights with financial guidance
- Real-time transaction data in recent activity
- Quick transaction entry form
- Enhanced empty state with helpful guidance
- Improved data visualization and analytics

### Offline Functionality
- Complete offline support with service workers
- IndexedDB for client-side data storage
- Background sync for data synchronization
- Offline form submissions with auto-save
- Progressive Web App capabilities

## Installation & Setup

### Prerequisites
- Python 3.8+
- MongoDB 4.4+
- Redis (optional, for caching)

### Environment Variables
```bash
SECRET_KEY=your-secret-key
MONGO_URI=mongodb://localhost:27017/ficodb
ADMIN_PASSWORD=admin-password
ADMIN_EMAIL=admin@example.com
FLASK_ENV=development
```

### Installation Steps
1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Set up environment variables
4. Initialize MongoDB database
5. Run the application: `python app.py`

## API Documentation

The application provides comprehensive REST APIs for:
- User authentication and management
- Budget CRUD operations
- Bill management and tracking
- Shopping list operations
- Transaction recording and retrieval
- Credit system management
- Offline data synchronization

## Contributing

This is a proprietary application. All development should follow:
- Code review process
- Security best practices
- Comprehensive testing
- Documentation updates
- Audit trail maintenance

## Support

For technical support or feature requests, contact the development team through the internal support channels.

---

**Version**: 2.1.0  
**Last Updated**: December 2024  
**License**: Proprietary - FICORE LABS LIMITED

