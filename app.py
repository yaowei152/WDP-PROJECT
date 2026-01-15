from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, extract 
from datetime import datetime, timedelta
import random
import os
import json 

# --- 1. SETUP & CONFIGURATION ---
app = Flask(__name__)
app.secret_key = 'your_secret_key_here' 

basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'business_data.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- 2. DATABASE MODELS ---

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False) 

class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    company = db.Column(db.String(100))

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date_placed = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50), default='Pending') 
    
    client = db.relationship('Client', backref=db.backref('orders', lazy=True))

class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_code = db.Column(db.String(50), unique=True, nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'))
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(50), default='Draft') 
    date_created = db.Column(db.DateTime, default=datetime.utcnow)
    date_due = db.Column(db.DateTime)
    
    client = db.relationship('Client', backref=db.backref('invoices', lazy=True))
    order = db.relationship('Order', backref=db.backref('invoice', uselist=False))

class AuditLog(db.Model):
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
    log = AuditLog(
        actor_type=actor_type, actor_id=actor_id, action=action,
        entity_type=entity_type, entity_id=entity_id, status=status, description=description
    )
    db.session.add(log)
    db.session.commit()

# --- 4. ROUTES ---

@app.route('/')
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
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
    if 'user_id' not in session: return redirect(url_for('login'))
    
    # --- Existing KPI Calculations ---
    total_invoices = Invoice.query.count()
    total_revenue = db.session.query(func.sum(Invoice.amount)).scalar() or 0
    paid_invoices = Invoice.query.filter_by(status='Paid').count()
    unpaid_invoices = Invoice.query.filter(Invoice.status.in_(['Unpaid', 'Overdue', 'Sent'])).count()
    avg_proc_time = "1.2 Days" 

    # --- Top Clients Logic ---
    top_clients = db.session.query(
        Client.name, func.sum(Invoice.amount)
    ).join(Invoice).group_by(Client.name).order_by(func.sum(Invoice.amount).desc()).limit(4).all()

    # --- Chart Data (Using Real DB Logic from previous step) ---
    current_year = datetime.now().year
    current_month = datetime.now().month

    # 1. Monthly Sales
    chart_invoice_months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sept', 'Oct', 'Nov', 'Dec']
    chart_invoice_reality = [0] * 12 
    monthly_sales = db.session.query(
        extract('month', Invoice.date_created).label('month'),
        func.sum(Invoice.amount).label('total')
    ).filter(extract('year', Invoice.date_created) == current_year).group_by('month').all()
    for month, total in monthly_sales:
        chart_invoice_reality[int(month)-1] = total
    chart_invoice_target = [20000] * 12

    # 2. YTD
    ytd_invoiced = db.session.query(func.sum(Order.amount)).filter(
        extract('year', Order.date_placed) == current_year, Order.status == 'Invoiced'
    ).scalar() or 0
    ytd_pending = db.session.query(func.sum(Order.amount)).filter(
        extract('year', Order.date_placed) == current_year, Order.status == 'Pending'
    ).scalar() or 0
    chart_orders_ytd_pct = [round(ytd_invoiced), round(ytd_pending)] if (ytd_invoiced + ytd_pending) > 0 else [0,100]

    # 3. MTD
    mtd_invoiced = db.session.query(func.sum(Order.amount)).filter(
        extract('year', Order.date_placed) == current_year, extract('month', Order.date_placed) == current_month, Order.status == 'Invoiced'
    ).scalar() or 0
    mtd_pending = db.session.query(func.sum(Order.amount)).filter(
        extract('year', Order.date_placed) == current_year, extract('month', Order.date_placed) == current_month, Order.status == 'Pending'
    ).scalar() or 0
    chart_orders_mtd_pct = [round(mtd_invoiced), round(mtd_pending)] if (mtd_invoiced + mtd_pending) > 0 else [0,100]

    # 4. Top Clients Progress
    top_clients_progress = []
    if top_clients:
        max_val = top_clients[0][1] if top_clients[0][1] > 0 else 1
        for client in top_clients:
            percent = min(round((client[1] / max_val) * 100), 100)
            top_clients_progress.append({'name': client[0], 'amount': client[1], 'percent': percent})

    # 5. Vol vs Service
    chart_vol_service_labels = []
    chart_vol_data = []
    chart_service_data = []
    for i in range(4, -1, -1):
        day = datetime.now() - timedelta(days=i)
        chart_vol_service_labels.append(day.strftime('%a'))
        chart_vol_data.append(Order.query.filter(func.date(Order.date_placed) == day.date()).count())
        chart_service_data.append(Invoice.query.filter(func.date(Invoice.date_created) == day.date()).count())

    # 6. Satisfaction
    chart_sat_labels = ['W1', 'W2', 'W3', 'W4', 'W5', 'W6', 'W7']
    chart_sat_data = [85, 82, 88, 84, 91, 87, 94]

    return render_template('dashboard.html', 
                           total_invoices=total_invoices, total_revenue=total_revenue,
                           paid_invoices=paid_invoices, unpaid_invoices=unpaid_invoices,
                           avg_proc_time=avg_proc_time, top_clients=top_clients,
                           chart_invoice_months=chart_invoice_months, chart_invoice_reality=chart_invoice_reality,
                           chart_invoice_target=chart_invoice_target, chart_orders_ytd_pct=chart_orders_ytd_pct,
                           chart_orders_mtd_pct=chart_orders_mtd_pct, top_clients_progress=top_clients_progress,
                           chart_sat_labels=chart_sat_labels, chart_sat_data=chart_sat_data,
                           chart_vol_service_labels=chart_vol_service_labels, chart_vol_data=chart_vol_data,
                           chart_service_data=chart_service_data)

@app.route('/orders')
def orders():
    if 'user_id' not in session: return redirect(url_for('login'))
    orders = Order.query.order_by(Order.date_placed.desc()).all()
    return render_template('orders.html', orders=orders)

@app.route('/invoices', methods=['GET'])
def invoices():
    if 'user_id' not in session: return redirect(url_for('login'))
    search_query = request.args.get('search', '')
    if search_query:
        invoices = Invoice.query.filter(Invoice.invoice_code.contains(search_query)).all()
    else:
        invoices = Invoice.query.order_by(Invoice.date_created.desc()).all()
    return render_template('invoices.html', invoices=invoices)

@app.route('/invoices/create/<int:order_id>', methods=['GET', 'POST'])
def create_invoice(order_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    order = Order.query.get_or_404(order_id)
    if request.method == 'POST':
        try:
            new_code = f"INV-{datetime.now().strftime('%Y%m%d')}-{random.randint(100,999)}"
            new_invoice = Invoice(
                invoice_code=new_code, order_id=order.id, client_id=order.client_id,
                amount=order.amount, status='Sent', date_due=datetime.utcnow() + timedelta(days=30)
            )
            db.session.add(new_invoice)
            order.status = 'Invoiced'
            db.session.commit()
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
    invoice = Invoice.query.get_or_404(invoice_id)
    return render_template('view_invoice.html', invoice=invoice)

# --- NEW ROUTE: EDIT INVOICE ---
@app.route('/invoices/edit/<int:invoice_id>', methods=['GET', 'POST'])
def edit_invoice(invoice_id):
    """Allows manual editing of invoice details and logs changes."""
    if 'user_id' not in session: return redirect(url_for('login'))
    
    invoice = Invoice.query.get_or_404(invoice_id)
    
    if request.method == 'POST':
        try:
            # Capture old values for Audit Log
            old_amount = invoice.amount
            old_status = invoice.status
            old_due_date = invoice.date_due.strftime('%Y-%m-%d')
            
            # Update with new values from form
            invoice.amount = float(request.form['amount'])
            invoice.status = request.form['status']
            invoice.date_due = datetime.strptime(request.form['date_due'], '%Y-%m-%d')
            
            # Determine what changed
            changes = []
            if old_amount != invoice.amount:
                changes.append(f"Amount: ${old_amount} -> ${invoice.amount}")
            if old_status != invoice.status:
                changes.append(f"Status: {old_status} -> {invoice.status}")
            if old_due_date != request.form['date_due']:
                changes.append(f"Due Date: {old_due_date} -> {request.form['date_due']}")
            
            db.session.commit()
            
            # Detailed Logging
            if changes:
                change_log = ", ".join(changes)
                log_action('User', session['username'], 'Invoice Edited', 'Invoice', invoice.invoice_code, 'Success', change_log)
                flash(f'Invoice {invoice.invoice_code} updated successfully.')
            else:
                flash('No changes detected.')
                
            return redirect(url_for('view_invoice', invoice_id=invoice.id))
            
        except Exception as e:
            db.session.rollback()
            log_action('User', session['username'], 'Invoice Edit Failed', 'Invoice', invoice.invoice_code, 'Failure', str(e))
            return redirect(url_for('error_page'))

    return render_template('edit_invoice.html', invoice=invoice)

# --- NEW ROUTE: DELETE INVOICE ---
@app.route('/invoices/delete/<int:invoice_id>', methods=['POST'])
def delete_invoice(invoice_id):
    """Deletes an invoice and logs specific details."""
    if 'user_id' not in session: return redirect(url_for('login'))
    
    invoice = Invoice.query.get_or_404(invoice_id)
    code = invoice.invoice_code
    
    try:
        # Construct detailed log BEFORE deletion
        details = f"Deleted Invoice {code}. Amount: ${invoice.amount}. Client: {invoice.client.name}. Order Ref: #{invoice.order_id}."
        
        # Reset linked order status if needed (Optional business logic)
        if invoice.order:
            invoice.order.status = 'Pending' # Revert order to pending so it can be re-invoiced if needed
        
        db.session.delete(invoice)
        db.session.commit()
        
        log_action('User', session['username'], 'Invoice Deleted', 'Invoice', code, 'Success', details)
        flash(f'Invoice {code} deleted successfully.')
        return redirect(url_for('invoices'))
        
    except Exception as e:
        db.session.rollback()
        log_action('User', session['username'], 'Invoice Delete Failed', 'Invoice', code, 'Failure', str(e))
        return redirect(url_for('error_page'))

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

# --- NEW ROUTE: AUDIT DETAILS ---
@app.route('/audit/view/<int:log_id>')
def audit_details(log_id):
    """Shows specific details for a single audit log entry."""
    if 'user_id' not in session: return redirect(url_for('login'))
    log = AuditLog.query.get_or_404(log_id)
    return render_template('audit_details.html', log=log)

@app.route('/error')
def error_page():
    return render_template('error.html')

@app.route('/guide')
def guide():
    return render_template('guide.html')

# --- 5. INITIALIZATION ---
with app.app_context():
    db.create_all()
    if not User.query.first():
        admin = User(username='admin', password='password123')
        db.session.add(admin)
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
    clients = Client.query.all()
    if not clients:
        c1 = Client(name="Alpha Corp", email="contact@alpha.com", company="Alpha Corp")
        c2 = Client(name="Beta Industries", email="accounts@beta.com", company="Beta Ind")
        db.session.add_all([c1, c2])
        db.session.commit()
        clients = [c1, c2]
    import random
    current_year = datetime.now().year
    # Historical
    for month in range(1, 13):
        if month <= datetime.now().month:
            for _ in range(random.randint(1, 3)):
                client = random.choice(clients)
                amount = random.randint(1000, 5000)
                date_event = datetime(current_year, month, random.randint(1, 28))
                order = Order(client_id=client.id, description=f"Service {month}", amount=amount, date_placed=date_event, status='Invoiced')
                db.session.add(order)
                db.session.commit()
                inv = Invoice(invoice_code=f"INV-{current_year}{month:02d}-{random.randint(100,999)}", order_id=order.id, client_id=client.id, amount=amount, status='Paid', date_created=date_event, date_due=date_event)
                db.session.add(inv)
    # Recent
    for i in range(5):
        day = datetime.now() - timedelta(days=i)
        for _ in range(random.randint(1, 3)):
            client = random.choice(clients)
            amt = random.randint(500, 1500)
            status = 'Pending' if random.choice([True, False]) else 'Invoiced'
            order = Order(client_id=client.id, description=f"Rush {i}", amount=amt, date_placed=day, status=status)
            db.session.add(order)
            if status == 'Invoiced':
                db.session.commit()
                inv = Invoice(invoice_code=f"INV-NOW-{random.randint(1000,9999)}", order_id=order.id, client_id=client.id, amount=amt, status='Sent', date_created=day, date_due=day)
                db.session.add(inv)
    db.session.commit()
    flash("Test Data Generated.")
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True)