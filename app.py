from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import random
import os
import json # Added json for passing data to charts

# --- 1. SETUP & CONFIGURATION ---
app = Flask(__name__)
app.secret_key = 'your_secret_key_here' # Needed for session management (login)

# Database Configuration (SQLite)
# This creates a file named 'business_data.db' in your folder automatically
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'business_data.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- 2. DATABASE MODELS (The Tables) ---

class User(db.Model):
    """Stores login details for the business admin."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False) 

class Client(db.Model):
    """Stores client info."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    company = db.Column(db.String(100))

class Order(db.Model):
    """Stores orders. If status is 'Pending', the AI can turn this into an Invoice."""
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date_placed = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50), default='Pending') # Pending, Invoiced
    
    # Relationship to access client details easily
    client = db.relationship('Client', backref=db.backref('orders', lazy=True))

class Invoice(db.Model):
    """Stores generated invoices."""
    id = db.Column(db.Integer, primary_key=True)
    invoice_code = db.Column(db.String(50), unique=True, nullable=False) # The "Specific Key" required
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'))
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(50), default='Draft') # Draft, Sent, Paid, Overdue
    date_created = db.Column(db.DateTime, default=datetime.utcnow)
    date_due = db.Column(db.DateTime)
    
    client = db.relationship('Client', backref=db.backref('invoices', lazy=True))
    order = db.relationship('Order', backref=db.backref('invoice', uselist=False))

class AuditLog(db.Model):
    """Stores the 'Very Important' Audit Log entries."""
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    actor_type = db.Column(db.String(50), default='System') 
    actor_id = db.Column(db.String(50))
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(50)) 
    entity_id = db.Column(db.String(50))
    status = db.Column(db.String(50)) 
    description = db.Column(db.String(255))

# --- 3. HELPER FUNCTIONS ---

def log_action(actor_type, actor_id, action, entity_type, entity_id, status, description):
    """Helper to save an action to the Audit Log table."""
    log = AuditLog(
        actor_type=actor_type, actor_id=actor_id, action=action,
        entity_type=entity_type, entity_id=entity_id, status=status, description=description
    )
    db.session.add(log)
    db.session.commit()

# --- 4. ROUTES (The Pages) ---

@app.route('/')
def home():
    """Redirects root URL to dashboard or login."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handles Login Logic."""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        # Simple check (In real life, use hashed passwords!)
        user = User.query.filter_by(username=username, password=password).first()
        if user:
            session['user_id'] = user.id
            session['username'] = user.username
            log_action('User', user.username, 'Login', 'Session', 'N/A', 'Success', 'User logged in successfully')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials')
            log_action('User', username, 'Login Failed', 'Session', 'N/A', 'Failure', 'Invalid password attempt')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    """Calculates KPIs and shows the Dashboard."""
    if 'user_id' not in session: return redirect(url_for('login'))
    
    # --- Existing KPI Calculations ---
    total_invoices = Invoice.query.count()
    total_revenue = db.session.query(db.func.sum(Invoice.amount)).scalar() or 0
    paid_invoices = Invoice.query.filter_by(status='Paid').count()
    unpaid_invoices = Invoice.query.filter(Invoice.status.in_(['Unpaid', 'Overdue', 'Sent'])).count()
    avg_proc_time = "1.2 Days" # Hardcoded for PoC

    # Top Clients Logic (Existing)
    top_clients = db.session.query(
        Client.name, db.func.sum(Invoice.amount)
    ).join(Invoice).group_by(Client.name).order_by(db.func.sum(Invoice.amount).desc()).limit(4).all()

    # --- New Data Preparation for Wireframe Charts (Simulated Data) ---
    # In a real scenario, these would be complex date-based queries.
    # We use simulated data here to match the visual requirements of the wireframe immediately.

    # 1. Invoiced Bar Chart Data (Monthly Comparison)
    chart_invoice_months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sept', 'Oct', 'Nov', 'Dec']
    # Simulated values to match the visual "Reality vs Target" look
    chart_invoice_reality = [15, 12, 18, 16, 21, 24, 19, 22, 28, 31, 26, 35] 
    chart_invoice_target = [14, 14, 16, 16, 20, 22, 20, 22, 25, 30, 28, 32]

    # 2. Orders Donut Charts Data (Simulating percentages)
    chart_orders_ytd_pct = [75, 25] # 75% achieved, 25% remaining
    chart_orders_mtd_pct = [60, 40] # 60% achieved, 40% remaining

    # 3. Top Clients Progress Bar Data
    # We calculate percentages based on the real top_clients data if available.
    top_clients_progress = []
    if top_clients and len(top_clients) > 0:
        # Find the highest value to calculate relative percentages
        max_val = top_clients[0][1] if top_clients[0][1] > 0 else 1
        for client in top_clients:
            # Calculate percentage relative to the top client
            percent = min(round((client[1] / max_val) * 100), 100)
            top_clients_progress.append({'name': client[0], 'amount': client[1], 'percent': percent})
    else:
        # Fallback dummy data if database is empty, so the UI looks correct
        top_clients_progress = [
             {'name': 'Client A (Demo)', 'amount': 5000, 'percent': 90},
             {'name': 'Client B (Demo)', 'amount': 4200, 'percent': 75},
             {'name': 'Client C (Demo)', 'amount': 3100, 'percent': 55},
             {'name': 'Client D (Demo)', 'amount': 1500, 'percent': 30},
         ]

    # 4. Customer Satisfaction Area Chart Data
    chart_sat_labels = ['W1', 'W2', 'W3', 'W4', 'W5', 'W6', 'W7']
    chart_sat_data = [85, 82, 88, 84, 91, 87, 94]

    # 5. Volume vs Service Level Stacked Bar Data
    chart_vol_service_labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
    chart_vol_data = [500, 600, 550, 580, 700]
    chart_service_data = [450, 580, 530, 560, 680]

    return render_template('dashboard.html', 
                           # Existing context
                           total_invoices=total_invoices,
                           total_revenue=total_revenue,
                           paid_invoices=paid_invoices,
                           unpaid_invoices=unpaid_invoices,
                           avg_proc_time=avg_proc_time,
                           top_clients=top_clients,
                           # New chart context
                           chart_invoice_months=chart_invoice_months,
                           chart_invoice_reality=chart_invoice_reality,
                           chart_invoice_target=chart_invoice_target,
                           chart_orders_ytd_pct=chart_orders_ytd_pct,
                           chart_orders_mtd_pct=chart_orders_mtd_pct,
                           top_clients_progress=top_clients_progress,
                           chart_sat_labels=chart_sat_labels,
                           chart_sat_data=chart_sat_data,
                           chart_vol_service_labels=chart_vol_service_labels,
                           chart_vol_data=chart_vol_data,
                           chart_service_data=chart_service_data
                           )

@app.route('/orders')
def orders():
    """Shows Order Management."""
    if 'user_id' not in session: return redirect(url_for('login'))
    orders = Order.query.order_by(Order.date_placed.desc()).all()
    return render_template('orders.html', orders=orders)

@app.route('/invoices', methods=['GET'])
def invoices():
    """Shows Invoice Management with Find Function."""
    if 'user_id' not in session: return redirect(url_for('login'))
    
    search_query = request.args.get('search', '')
    if search_query:
        # The 'Find Function' required by 3.4
        invoices = Invoice.query.filter(Invoice.invoice_code.contains(search_query)).all()
    else:
        invoices = Invoice.query.order_by(Invoice.date_created.desc()).all()
        
    return render_template('invoices.html', invoices=invoices)

@app.route('/invoices/create/<int:order_id>', methods=['GET', 'POST'])
def create_invoice(order_id):
    """The AI Feature: Auto-generates invoice from Order Data."""
    if 'user_id' not in session: return redirect(url_for('login'))
    
    order = Order.query.get_or_404(order_id)
    
    if request.method == 'POST':
        try:
            # Auto-generate unique code
            new_code = f"INV-{datetime.now().strftime('%Y%m%d')}-{random.randint(100,999)}"
            
            # Create Invoice Object
            new_invoice = Invoice(
                invoice_code=new_code,
                order_id=order.id,
                client_id=order.client_id,
                amount=order.amount,
                status='Sent',
                date_due=datetime.utcnow() + timedelta(days=30)
            )
            db.session.add(new_invoice)
            
            # Update Order Status
            order.status = 'Invoiced'
            db.session.commit()
            
            # Log it (3.5)
            log_action('System', 'AI-Invoice-Bot', 'Invoice Generated', 'Invoice', new_code, 'Success', f'Auto-generated invoice for Order #{order.id}')
            
            flash(f'Invoice {new_code} generated successfully!')
            return redirect(url_for('invoices'))
        except Exception as e:
            db.session.rollback()
            log_action('System', 'AI-Invoice-Bot', 'Invoice Generation Failed', 'Invoice', 'N/A', 'Failure', str(e))
            return redirect(url_for('error_page'))
            
    return render_template('create_invoice.html', order=order)

@app.route('/invoices/view/<int:invoice_id>')
def view_invoice(invoice_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    
    # Get invoice or return 404 error if not found
    invoice = Invoice.query.get_or_404(invoice_id)
    
    return render_template('view_invoice.html', invoice=invoice)

@app.route('/audit')
def audit_log():
    """Shows Audit Log with Filters."""
    if 'user_id' not in session: return redirect(url_for('login'))
    
    status_filter = request.args.get('status')
    action_filter = request.args.get('action')
    
    query = AuditLog.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    if action_filter:
        query = query.filter_by(action=action_filter)
        
    logs = query.order_by(AuditLog.timestamp.desc()).all()
    return render_template('audit_log.html', logs=logs)

@app.route('/error')
def error_page():
    return render_template('error.html')

@app.route('/guide')
def guide():
    return render_template('guide.html')

# --- 5. INITIALIZATION (Runs once to build DB) ---
# Note: In Flask 2.3+, 'before_first_request' is deprecated. 
# We use this check to create tables if they don't exist when the script runs.

with app.app_context():
    db.create_all()
    # Create Admin if not exists
    if not User.query.first():
        print("Creating default admin user...")
        admin = User(username='admin', password='password123')
        db.session.add(admin)
        
        # Dummy Data
        c1 = Client(name='TechSolutions Pte Ltd', email='contact@techsol.sg', company='TechSolutions')
        c2 = Client(name='Green Grocer', email='boss@greengrocer.com', company='Green Grocer')
        db.session.add_all([c1, c2])
        db.session.commit()
        
        o1 = Order(client_id=c1.id, description='IT Consultation - Q1', amount=5000.00, status='Pending')
        o2 = Order(client_id=c2.id, description='Bulk Vegetable Order', amount=1200.50, status='Invoiced')
        db.session.add_all([o1, o2])
        db.session.commit()
        
        i1 = Invoice(invoice_code='INV-20250115-001', order_id=o2.id, client_id=c2.id, amount=1200.50, status='Paid', date_due=datetime.utcnow())
        db.session.add(i1)
        db.session.commit()
        
        log_action('System', 'Auto-Invoice-Service', 'Invoice Generated', 'Invoice', 'INV-20250115-001', 'Success', 'Initial Data Load')

@app.route('/generate_test_data')
def generate_test_data():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    # Create a dummy client if none exists, or pick the first one
    client = Client.query.first()
    if not client:
        client = Client(name="Test Client", email="test@example.com", company="Tester Co.")
        db.session.add(client)
        db.session.commit()
    
    # Create 3 new Random Orders
    import random
    descriptions = ["Web Design Service", "Server Maintenance", "Consultation Fee", "Software License", "Hardware Repair"]
    
    for _ in range(3):
        random_amount = random.randint(100, 5000) + 0.50
        new_order = Order(
            client_id=client.id,
            description=random.choice(descriptions),
            amount=random_amount,
            status='Pending'  # Important: Must be 'Pending' so we can generate an invoice for it!
        )
        db.session.add(new_order)
    
    db.session.commit()
    flash("3 New Test Orders Created! Go to 'Orders' to generate invoices for them.")
    return redirect(url_for('orders'))

if __name__ == '__main__':
    app.run(debug=True)