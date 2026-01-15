from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, extract, or_
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

def get_change(current, previous):
    """Calculates percentage change safely."""
    if previous == 0:
        return 100 if current > 0 else 0
    return ((current - previous) / previous) * 100

def format_k(value):
    """Formats large numbers (e.g. 1500 -> 1.5k, 1000000 -> 1.0M)"""
    if value >= 1000000: return f"{value/1000000:.1f}M"
    if value >= 1000: return f"{value/1000:.1f}k"
    return str(value)

# --- 4. ROUTES ---

@app.route('/')
def home():
    if 'user_id' not in session: return redirect(url_for('login'))
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
    
    now = datetime.now()
    current_year = now.year
    last_year = current_year - 1
    current_month = now.month
    
    last_month_date = now.replace(day=1) - timedelta(days=1)
    prev_month = last_month_date.month
    prev_month_year = last_month_date.year

    # KPI 1: Orders
    total_orders = Order.query.count()
    total_orders_prev = Order.query.filter(Order.date_placed < now - timedelta(days=30)).count()
    order_growth = get_change(total_orders, total_orders_prev)

    # KPI 2: Sales
    total_sales = db.session.query(func.sum(Invoice.amount)).scalar() or 0
    sales_prev = db.session.query(func.sum(Invoice.amount)).filter(Invoice.date_created < now.replace(day=1)).scalar() or 0
    sales_growth = get_change(total_sales, sales_prev)

    # KPI 3: Products/Paid
    products_sold = Invoice.query.filter_by(status='Paid').count()
    products_prev = Invoice.query.filter(Invoice.status=='Paid', Invoice.date_created < now - timedelta(days=30)).count()
    product_growth = get_change(products_sold, products_prev)

    # KPI 4: Customers
    new_customers = Client.query.count() 
    customer_growth = 1.29 

    # Stats: YTD
    ytd_sales = db.session.query(func.sum(Order.amount)).filter(extract('year', Order.date_placed) == current_year).scalar() or 0
    last_ytd_sales = db.session.query(func.sum(Order.amount)).filter(extract('year', Order.date_placed) == last_year).scalar() or 0
    ytd_sales_growth = ytd_sales - last_ytd_sales

    ytd_count = Order.query.filter(extract('year', Order.date_placed) == current_year).count()
    last_ytd_count = Order.query.filter(extract('year', Order.date_placed) == last_year).count()
    ytd_count_growth = ytd_count - last_ytd_count

    # Stats: MTD
    mtd_sales = db.session.query(func.sum(Order.amount)).filter(
        extract('year', Order.date_placed) == current_year, 
        extract('month', Order.date_placed) == current_month
    ).scalar() or 0
    
    last_mtd_sales = db.session.query(func.sum(Order.amount)).filter(
        extract('year', Order.date_placed) == prev_month_year, 
        extract('month', Order.date_placed) == prev_month
    ).scalar() or 0
    mtd_sales_diff = mtd_sales - last_mtd_sales

    mtd_count = Order.query.filter(
        extract('year', Order.date_placed) == current_year, 
        extract('month', Order.date_placed) == current_month
    ).count()

    last_mtd_count = Order.query.filter(
        extract('year', Order.date_placed) == prev_month_year, 
        extract('month', Order.date_placed) == prev_month
    ).count()
    mtd_count_diff = mtd_count - last_mtd_count

    # Graph Data
    chart_invoice_months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sept', 'Oct', 'Nov', 'Dec']
    chart_invoice_reality = [0] * 12 
    monthly_sales_query = db.session.query(
        extract('month', Invoice.date_created).label('month'),
        func.sum(Invoice.amount).label('total')
    ).filter(extract('year', Invoice.date_created) == current_year).group_by('month').all()
    
    for m, total in monthly_sales_query:
        chart_invoice_reality[int(m)-1] = total
        
    chart_invoice_target = [20000] * 12 

    ytd_invoiced_amt = db.session.query(func.sum(Order.amount)).filter(
        extract('year', Order.date_placed) == current_year, Order.status == 'Invoiced'
    ).scalar() or 0
    ytd_pending_amt = db.session.query(func.sum(Order.amount)).filter(
        extract('year', Order.date_placed) == current_year, Order.status == 'Pending'
    ).scalar() or 0
    chart_orders_ytd_pct = [round(ytd_invoiced_amt), round(ytd_pending_amt)]
    if sum(chart_orders_ytd_pct) == 0: chart_orders_ytd_pct = [0, 1]

    mtd_invoiced_amt = db.session.query(func.sum(Order.amount)).filter(
        extract('year', Order.date_placed) == current_year, extract('month', Order.date_placed) == current_month, Order.status == 'Invoiced'
    ).scalar() or 0
    mtd_pending_amt = db.session.query(func.sum(Order.amount)).filter(
        extract('year', Order.date_placed) == current_year, extract('month', Order.date_placed) == current_month, Order.status == 'Pending'
    ).scalar() or 0
    chart_orders_mtd_pct = [round(mtd_invoiced_amt), round(mtd_pending_amt)]
    if sum(chart_orders_mtd_pct) == 0: chart_orders_mtd_pct = [0, 1]

    top_clients_query = db.session.query(
        Client.name, func.sum(Invoice.amount)
    ).join(Invoice).group_by(Client.name).order_by(func.sum(Invoice.amount).desc()).limit(4).all()
    
    top_clients_progress = []
    if top_clients_query:
        max_val = top_clients_query[0][1] if top_clients_query[0][1] > 0 else 1
        for client in top_clients_query:
            percent = min(round((client[1] / max_val) * 100), 100)
            top_clients_progress.append({'name': client[0], 'amount': client[1], 'percent': percent})

    chart_vol_service_labels = []
    chart_vol_data = []
    chart_service_data = []
    for i in range(4, -1, -1):
        day = now - timedelta(days=i)
        chart_vol_service_labels.append(day.strftime('%a'))
        chart_vol_data.append(Order.query.filter(func.date(Order.date_placed) == day.date()).count())
        chart_service_data.append(Invoice.query.filter(func.date(Invoice.date_created) == day.date()).count())
    
    chart_sat_labels = ['W1', 'W2', 'W3', 'W4', 'W5', 'W6', 'W7']
    chart_sat_data = [85, 82, 88, 84, 91, 87, 94]

    return render_template('dashboard.html',
        total_orders=format_k(total_orders), order_growth=order_growth,
        total_sales=format_k(total_sales), sales_growth=sales_growth,
        products_sold=products_sold, product_growth=product_growth,
        new_customers=new_customers, customer_growth=customer_growth,
        ytd_sales=format_k(ytd_sales), ytd_sales_growth=format_k(abs(ytd_sales_growth)), ytd_pos=(ytd_sales_growth>=0),
        ytd_count=format_k(ytd_count), ytd_count_growth=format_k(abs(ytd_count_growth)), ytd_count_pos=(ytd_count_growth>=0),
        mtd_sales=format_k(mtd_sales), mtd_sales_diff=format_k(abs(mtd_sales_diff)), mtd_pos=(mtd_sales_diff>=0),
        mtd_count=mtd_count, mtd_count_diff=abs(mtd_count_diff), mtd_count_pos=(mtd_count_diff>=0),
        chart_invoice_months=chart_invoice_months, chart_invoice_reality=chart_invoice_reality, chart_invoice_target=chart_invoice_target,
        chart_orders_ytd_pct=chart_orders_ytd_pct, chart_orders_mtd_pct=chart_orders_mtd_pct,
        top_clients_progress=top_clients_progress,
        chart_sat_labels=chart_sat_labels, chart_sat_data=chart_sat_data,
        chart_vol_service_labels=chart_vol_service_labels, chart_vol_data=chart_vol_data, chart_service_data=chart_service_data
    )

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

@app.route('/invoices/edit/<int:invoice_id>', methods=['GET', 'POST'])
def edit_invoice(invoice_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    invoice = Invoice.query.get_or_404(invoice_id)
    if request.method == 'POST':
        try:
            old_amount = invoice.amount
            old_status = invoice.status
            old_due_date = invoice.date_due.strftime('%Y-%m-%d')
            
            invoice.amount = float(request.form['amount'])
            invoice.status = request.form['status']
            invoice.date_due = datetime.strptime(request.form['date_due'], '%Y-%m-%d')
            
            changes = []
            if old_amount != invoice.amount: changes.append(f"Amount: ${old_amount} -> ${invoice.amount}")
            if old_status != invoice.status: changes.append(f"Status: {old_status} -> {invoice.status}")
            if old_due_date != request.form['date_due']: changes.append(f"Due Date: {old_due_date} -> {request.form['date_due']}")
            
            db.session.commit()
            if changes:
                log_action('User', session['username'], 'Invoice Edited', 'Invoice', invoice.invoice_code, 'Success', ", ".join(changes))
                flash(f'Invoice {invoice.invoice_code} updated successfully.')
            else:
                flash('No changes detected.')
            return redirect(url_for('view_invoice', invoice_id=invoice.id))
        except Exception as e:
            db.session.rollback()
            log_action('User', session['username'], 'Invoice Edit Failed', 'Invoice', invoice.invoice_code, 'Failure', str(e))
            return redirect(url_for('error_page'))

@app.route('/invoices/delete/<int:invoice_id>', methods=['POST'])
def delete_invoice(invoice_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    invoice = Invoice.query.get_or_404(invoice_id)
    code = invoice.invoice_code
    try:
        details = f"Deleted Invoice {code}. Amount: ${invoice.amount}. Client: {invoice.client.name}. Order Ref: #{invoice.order_id}."
        if invoice.order: invoice.order.status = 'Pending'
        db.session.delete(invoice)
        db.session.commit()
        log_action('User', session['username'], 'Invoice Deleted', 'Invoice', code, 'Success', details)
        flash(f'Invoice {code} deleted successfully.')
        return redirect(url_for('invoices'))
    except Exception as e:
        db.session.rollback()
        log_action('User', session['username'], 'Invoice Delete Failed', 'Invoice', code, 'Failure', str(e))
        return redirect(url_for('error_page'))

# --- AUDIT LOG ROUTE (UPDATED) ---
@app.route('/audit')
def audit_log():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    # Get filters from URL parameters
    search_q = request.args.get('q', '')
    action_filter = request.args.get('action_type', '')
    
    query = AuditLog.query
    
    # Apply Search Filter (matches description, action, actor, or entity ID)
    if search_q:
        search_term = f"%{search_q}%"
        query = query.filter(
            or_(
                AuditLog.description.like(search_term),
                AuditLog.action.like(search_term),
                AuditLog.actor_id.like(search_term),
                AuditLog.entity_id.like(search_term)
            )
        )
    
    # Apply Dropdown Action Filter
    if action_filter and action_filter != 'All':
        query = query.filter(AuditLog.action == action_filter)

    logs = query.order_by(AuditLog.timestamp.desc()).all()
    
    # Get unique actions for the dropdown
    unique_actions = [r.action for r in db.session.query(AuditLog.action).distinct()]
    
    return render_template('audit_log.html', logs=logs, unique_actions=unique_actions)

@app.route('/audit/view/<int:log_id>')
def audit_details(log_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    log = AuditLog.query.get_or_404(log_id)
    return render_template('audit_details.html', log=log)

@app.route('/error')
def error_page():
    return render_template('error.html')

@app.route('/guide')
def guide():
    return render_template('guide.html')

# --- DATA GENERATOR (UPDATED - Fashion Theme) ---

@app.route('/generate_bulk_data')
def generate_bulk_data():
    """Generates 150+ records spanning 2 years. Access via URL."""
    if 'user_id' not in session: return redirect(url_for('login'))
    
    # 1. Clothing & Fashion Clients
    client_names = [
        "Vogue Styles", "Urban Trends Boutique", "Silk & Cotton Co", "Velvet Runway",
        "Modern Menswear", "Chic Streetwear", "Luxe Fabrics Ltd", "Denim Supply Depot",
        "Kids Corner Fashion", "Summer Breeze Apparel", "Winter Warmth Gear", "Athletic Aesthetics",
        "Vintage Threads", "Haute Couture House", "Basic Essentials", "Fashion Forward Inc"
    ]
    
    clients = []
    for name in client_names:
        exists = Client.query.filter_by(name=name).first()
        if not exists:
            # Create cleaner emails
            email_slug = name.replace(' ', '').replace('&', 'and').lower()
            c = Client(name=name, email=f"contact@{email_slug}.com", company=name)
            db.session.add(c)
            clients.append(c)
        else:
            clients.append(exists)
    db.session.commit()

    # 2. Fashion Order Descriptions
    descriptions = [
        "Summer Collection Shipment", "Bulk T-Shirts Printing", "Winter Coats Manufacturing", 
        "Silk Scarf Production", "Denim Jeans Supply", "Fashion Photoshoot Styling", 
        "Runway Accessories", "Custom Embroidery Service", "Leather Jacket Order", 
        "Sustainable Cotton Fabrics", "Activewear Line Launch", "Vintage Dress Restoration"
    ]
    
    start_date = datetime.now() - timedelta(days=730) 
    end_date = datetime.now()
    
    for _ in range(150): 
        days_between = (end_date - start_date).days
        order_date = start_date + timedelta(days=random.randrange(days_between))
        
        client = random.choice(clients)
        desc = random.choice(descriptions)
        # Amounts vary by type (simulated)
        if "Bulk" in desc or "Supply" in desc:
            amount = random.uniform(2000, 15000)
        else:
            amount = random.uniform(500, 4000)
        
        status = 'Invoiced' if random.random() > 0.3 else 'Pending'
        
        o = Order(client_id=client.id, description=desc, amount=amount, date_placed=order_date, status=status)
        db.session.add(o)
        db.session.commit()
        
        if status == 'Invoiced':
            inv_code = f"INV-{order_date.strftime('%Y%m')}-{random.randint(1000,9999)}"
            inv_status = 'Paid' if random.random() > 0.2 else 'Sent'
            
            inv = Invoice(
                invoice_code=inv_code,
                order_id=o.id,
                client_id=client.id,
                amount=amount,
                status=inv_status,
                date_created=order_date + timedelta(minutes=30),
                date_due=order_date + timedelta(days=30)
            )
            db.session.add(inv)
            
    db.session.commit()
    flash("Success! Added 150+ fashion-related mock orders and invoices.")
    return redirect(url_for('dashboard'))

# --- 6. INITIALIZATION ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not User.query.first():
            admin = User(username='admin', password='password123')
            db.session.add(admin)
            db.session.commit()
    app.run(debug=True)