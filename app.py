from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, extract, or_, text
from datetime import datetime, timedelta
from functools import wraps
import random
import os
import json 

# --- 1. SETUP & CONFIGURATION ---
app = Flask(__name__)
app.secret_key = 'your_secret_key_here' 

basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, 'business_data.db')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- 2. DATABASE MODELS ---

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    custom_id = db.Column(db.String(50), unique=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False) 
    role = db.Column(db.String(20), default='Staff') 
    is_suspended = db.Column(db.Boolean, default=False)
    must_change_password = db.Column(db.Boolean, default=False)

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
    try:
        log = AuditLog(actor_type=actor_type, actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id, status=status, description=description)
        db.session.add(log)
        db.session.commit()
    except: db.session.rollback()

def get_change(current, previous):
    if previous == 0: return 100 if current > 0 else 0
    return ((current - previous) / previous) * 100

def format_k(value):
    if value >= 1000000: return f"{value/1000000:.1f}M"
    if value >= 1000: return f"{value/1000:.1f}k"
    return str(value)

@app.before_request
def load_user():
    g.user = None
    if 'user_id' in session: g.user = User.query.get(session['user_id'])

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not g.user or g.user.role != 'SuperAdmin':
            flash("Access Denied: You do not have permission to view this page.", "danger")
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def operator_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not g.user or g.user.role == 'Staff':
            flash("Access Denied: Staff accounts cannot perform this action.", "danger")
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

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
            if user.is_suspended:
                flash('Your account has been suspended. Please contact the Super Admin.')
                return render_template('login.html')
            session['user_id'] = user.id
            if user.must_change_password: return redirect(url_for('change_password'))
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        new_pass = request.form['new_password']
        confirm_pass = request.form['confirm_password']
        if new_pass != confirm_pass or len(new_pass) < 4:
            flash('Invalid password or mismatch.')
            return redirect(url_for('change_password'))
        user.password = new_pass
        user.must_change_password = False 
        db.session.commit()
        return redirect(url_for('dashboard'))
    return render_template('change_password.html', user=user)

# --- ORDERS ROUTE ---
@app.route('/orders')
def orders():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    search_q = request.args.get('search', '')
    status_filter = request.args.get('status', 'All')
    sort_by = request.args.get('sort', 'date_desc')

    query = Order.query

    if search_q:
        search_term = f"%{search_q}%"
        query = query.join(Client).filter(
            or_(
                Client.name.like(search_term),
                Order.description.like(search_term),
                func.cast(Order.id, db.String).like(search_term)
            )
        )

    if status_filter != 'All':
        query = query.filter(Order.status == status_filter)

    if sort_by == 'price_high':
        query = query.order_by(Order.amount.desc())
    elif sort_by == 'price_low':
        query = query.order_by(Order.amount.asc())
    elif sort_by == 'date_asc':
        query = query.order_by(Order.date_placed.asc())
    else: 
        query = query.order_by(Order.date_placed.desc())

    orders = query.all()
    return render_template('orders.html', orders=orders)

# --- INVOICE ROUTES ---
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
@operator_required
def create_invoice(order_id):
    order = Order.query.get_or_404(order_id)
    if request.method == 'POST':
        try:
            new_code = f"INV-{datetime.now().strftime('%Y%m%d')}-{random.randint(100,999)}"
            new_invoice = Invoice(invoice_code=new_code, order_id=order.id, client_id=order.client_id, amount=order.amount, status='Sent', date_due=datetime.utcnow() + timedelta(days=30))
            db.session.add(new_invoice)
            order.status = 'Invoiced'
            db.session.commit()
            log_action('System', 'AI-Invoice-Bot', 'Invoice Generated', 'Invoice', new_code, 'Success', f'Auto-generated invoice for Order #{order.id}')
            flash(f'Invoice {new_code} generated successfully!')
            return redirect(url_for('invoices'))
        except Exception as e:
            db.session.rollback()
            return redirect(url_for('error_page'))
    return render_template('create_invoice.html', order=order)

@app.route('/invoices/view/<int:invoice_id>')
def view_invoice(invoice_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    invoice = Invoice.query.get_or_404(invoice_id)
    return render_template('view_invoice.html', invoice=invoice)

@app.route('/invoices/edit/<int:invoice_id>', methods=['GET', 'POST'])
@admin_required
def edit_invoice(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    if request.method == 'POST':
        try:
            invoice.amount = float(request.form['amount'])
            invoice.status = request.form['status']
            invoice.date_due = datetime.strptime(request.form['date_due'], '%Y-%m-%d')
            db.session.commit()
            log_action('SuperAdmin', session.get('username'), 'Invoice Edited', 'Invoice', invoice.invoice_code, 'Success', "Updated invoice details")
            flash(f'Invoice {invoice.invoice_code} updated successfully.')
            return redirect(url_for('view_invoice', invoice_id=invoice.id))
        except:
            db.session.rollback()
            return redirect(url_for('error_page'))
    return render_template('edit_invoice.html', invoice=invoice)

@app.route('/invoices/delete/<int:invoice_id>', methods=['POST'])
@admin_required
def delete_invoice(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    try:
        if invoice.order: invoice.order.status = 'Pending'
        db.session.delete(invoice)
        db.session.commit()
        log_action('SuperAdmin', session.get('username'), 'Invoice Deleted', 'Invoice', invoice.invoice_code, 'Success', "Deleted invoice")
        flash('Invoice deleted successfully.')
        return redirect(url_for('invoices'))
    except:
        db.session.rollback()
        return redirect(url_for('error_page'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    if User.query.get(session['user_id']).must_change_password: return redirect(url_for('change_password'))
    
    now = datetime.now()
    current_year = now.year
    last_year = current_year - 1
    current_month = now.month
    prev_month_date = now.replace(day=1) - timedelta(days=1)
    prev_month = prev_month_date.month
    prev_month_year = prev_month_date.year

    # KPI 1
    total_orders = Order.query.count()
    total_orders_prev = Order.query.filter(Order.date_placed < now - timedelta(days=30)).count()
    order_growth = get_change(total_orders, total_orders_prev)

    # KPI 2
    total_sales = db.session.query(func.sum(Invoice.amount)).scalar() or 0
    sales_prev = db.session.query(func.sum(Invoice.amount)).filter(Invoice.date_created < now.replace(day=1)).scalar() or 0
    sales_growth = get_change(total_sales, sales_prev)

    # KPI 3
    products_sold = Invoice.query.filter_by(status='Paid').count()
    products_prev = Invoice.query.filter(Invoice.status=='Paid', Invoice.date_created < now - timedelta(days=30)).count()
    product_growth = get_change(products_sold, products_prev)

    # KPI 4
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
    mtd_sales = db.session.query(func.sum(Order.amount)).filter(extract('year', Order.date_placed) == current_year, extract('month', Order.date_placed) == current_month).scalar() or 0
    last_mtd_sales = db.session.query(func.sum(Order.amount)).filter(extract('year', Order.date_placed) == prev_month_year, extract('month', Order.date_placed) == prev_month).scalar() or 0
    mtd_sales_diff = mtd_sales - last_mtd_sales

    mtd_count = Order.query.filter(extract('year', Order.date_placed) == current_year, extract('month', Order.date_placed) == current_month).count()
    last_mtd_count = Order.query.filter(extract('year', Order.date_placed) == prev_month_year, extract('month', Order.date_placed) == prev_month).count()
    mtd_count_diff = mtd_count - last_mtd_count

    # Graph Data
    chart_invoice_months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sept', 'Oct', 'Nov', 'Dec']
    chart_invoice_reality = [0] * 12 
    monthly_sales_query = db.session.query(extract('month', Invoice.date_created), func.sum(Invoice.amount)).filter(extract('year', Invoice.date_created) == current_year).group_by(extract('month', Invoice.date_created)).all()
    for m, total in monthly_sales_query: chart_invoice_reality[int(m)-1] = total
        
    chart_invoice_target = [20000] * 12 

    ytd_invoiced_amt = db.session.query(func.sum(Order.amount)).filter(extract('year', Order.date_placed) == current_year, Order.status == 'Invoiced').scalar() or 0
    ytd_pending_amt = db.session.query(func.sum(Order.amount)).filter(extract('year', Order.date_placed) == current_year, Order.status == 'Pending').scalar() or 0
    chart_orders_ytd_pct = [round(ytd_invoiced_amt), round(ytd_pending_amt)]
    if sum(chart_orders_ytd_pct) == 0: chart_orders_ytd_pct = [0, 1]

    mtd_invoiced_amt = db.session.query(func.sum(Order.amount)).filter(extract('year', Order.date_placed) == current_year, extract('month', Order.date_placed) == current_month, Order.status == 'Invoiced').scalar() or 0
    mtd_pending_amt = db.session.query(func.sum(Order.amount)).filter(extract('year', Order.date_placed) == current_year, extract('month', Order.date_placed) == current_month, Order.status == 'Pending').scalar() or 0
    chart_orders_mtd_pct = [round(mtd_invoiced_amt), round(mtd_pending_amt)]
    if sum(chart_orders_mtd_pct) == 0: chart_orders_mtd_pct = [0, 1]

    top_clients_query = db.session.query(Client.name, func.sum(Invoice.amount)).join(Invoice).group_by(Client.name).order_by(func.sum(Invoice.amount).desc()).limit(4).all()
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
        chart_sat_labels=['W1','W2','W3','W4','W5','W6','W7'], chart_sat_data=[85,82,88,84,91,87,94],
        chart_vol_service_labels=chart_vol_service_labels, chart_vol_data=chart_vol_data, chart_service_data=chart_service_data
    )

# --- AUDIT ROUTES (FIXED) ---
@app.route('/audit')
def audit_log():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    search_q = request.args.get('q', '')
    action_filter = request.args.get('action_type', '')
    
    query = AuditLog.query
    if search_q:
        search_term = f"%{search_q}%"
        query = query.filter(or_(AuditLog.description.like(search_term), AuditLog.action.like(search_term), AuditLog.actor_id.like(search_term), AuditLog.entity_id.like(search_term)))
    
    if action_filter and action_filter != 'All':
        query = query.filter(AuditLog.action == action_filter)

    logs = query.order_by(AuditLog.timestamp.desc()).all()
    # Fixed: Restored logic to populate dropdown
    unique_actions = [r.action for r in db.session.query(AuditLog.action).distinct()]
    
    return render_template('audit_log.html', logs=logs, unique_actions=unique_actions)

# This was missing and caused the crash!
@app.route('/audit/view/<int:log_id>')
def audit_details(log_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    log = AuditLog.query.get_or_404(log_id)
    return render_template('audit_details.html', log=log)

# --- ADMIN PANEL ROUTES ---
@app.route('/admin/panel')
@admin_required
def admin_panel():
    search_q = request.args.get('q', '')
    query = User.query
    if search_q: query = query.filter(User.custom_id.like(f"%{search_q}%"))
    users = query.all()
    return render_template('admin_panel.html', users=users)

@app.route('/admin/create', methods=['GET', 'POST'])
@admin_required
def create_admin():
    if request.method == 'POST':
        if User.query.filter_by(username=request.form['username']).first():
            flash('Username already exists.')
            return redirect(url_for('create_admin'))
        
        count = User.query.count() + 1
        new_user = User(
            custom_id=f"USR-{datetime.now().year}-{count:03d}",
            username=request.form['username'],
            password=request.form['password'],
            role=request.form['role'],
            must_change_password=True
        )
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('admin_panel'))
    return render_template('admin_create.html')

@app.route('/admin/edit/<int:user_id>', methods=['GET', 'POST'])
@admin_required
def edit_admin(user_id):
    user = User.query.get(user_id)
    if request.method == 'POST':
        user.role = request.form['role']
        db.session.commit()
        return redirect(url_for('admin_panel'))
    return render_template('admin_edit.html', user=user)

@app.route('/admin/reset_password/<int:user_id>', methods=['POST'])
@admin_required
def reset_password(user_id):
    user = User.query.get(user_id)
    user.password = request.form['temp_password']
    new_username = request.form.get('new_username')
    if new_username: user.username = new_username
    user.must_change_password = True
    db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/suspend/<int:user_id>', methods=['POST'])
@admin_required
def suspend_admin(user_id):
    user = User.query.get(user_id)
    user.is_suspended = not user.is_suspended
    db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete/<int:user_id>', methods=['POST'])
@admin_required
def delete_admin(user_id):
    db.session.delete(User.query.get(user_id))
    db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/generate_bulk_data')
@operator_required
def generate_bulk_data():
    client_names = ["Vogue Styles", "Urban Trends Boutique", "Silk & Cotton Co", "Velvet Runway", "Modern Menswear", "Chic Streetwear", "Luxe Fabrics Ltd", "Denim Supply Depot", "Kids Corner Fashion", "Summer Breeze Apparel", "Winter Warmth Gear", "Athletic Aesthetics", "Vintage Threads", "Haute Couture House", "Basic Essentials", "Fashion Forward Inc"]
    clients = []
    for name in client_names:
        exists = Client.query.filter_by(name=name).first()
        if not exists:
            email_slug = name.replace(' ', '').replace('&', 'and').lower()
            c = Client(name=name, email=f"contact@{email_slug}.com", company=name)
            db.session.add(c)
            clients.append(c)
        else:
            clients.append(exists)
    db.session.commit()
    descriptions = ["Summer Collection Shipment", "Bulk T-Shirts Printing", "Winter Coats Manufacturing", "Silk Scarf Production", "Denim Jeans Supply", "Fashion Photoshoot Styling", "Runway Accessories", "Custom Embroidery Service", "Leather Jacket Order", "Sustainable Cotton Fabrics", "Activewear Line Launch", "Vintage Dress Restoration"]
    start_date = datetime.now() - timedelta(days=730) 
    end_date = datetime.now()
    for _ in range(150): 
        days_between = (end_date - start_date).days
        order_date = start_date + timedelta(days=random.randrange(days_between))
        client = random.choice(clients)
        desc = random.choice(descriptions)
        if "Bulk" in desc or "Supply" in desc: amount = random.uniform(2000, 15000)
        else: amount = random.uniform(500, 4000)
        status = 'Invoiced' if random.random() > 0.3 else 'Pending'
        o = Order(client_id=client.id, description=desc, amount=amount, date_placed=order_date, status=status)
        db.session.add(o)
        db.session.commit()
        if status == 'Invoiced':
            inv_code = f"INV-{order_date.strftime('%Y%m')}-{random.randint(1000,9999)}"
            inv_status = 'Paid' if random.random() > 0.2 else 'Sent'
            inv = Invoice(invoice_code=inv_code, order_id=o.id, client_id=client.id, amount=amount, status=inv_status, date_created=order_date + timedelta(minutes=30), date_due=order_date + timedelta(days=30))
            db.session.add(inv)
    db.session.commit()
    flash("Success! Added 150+ fashion-related mock orders and invoices.")
    return redirect(url_for('dashboard'))

@app.route('/guide')
def guide(): return render_template('guide.html')

@app.route('/error')
def error_page(): return render_template('error.html')

if __name__ == '__main__':
    with app.app_context():
        # Schema Check & Migration
        try:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE user ADD COLUMN role VARCHAR(20) DEFAULT 'Staff'"))
                conn.execute(text("ALTER TABLE user ADD COLUMN is_suspended BOOLEAN DEFAULT 0"))
                conn.execute(text("ALTER TABLE user ADD COLUMN custom_id VARCHAR(50)"))
                conn.execute(text("ALTER TABLE user ADD COLUMN must_change_password BOOLEAN DEFAULT 0"))
                conn.execute(text("UPDATE user SET role='SuperAdmin' WHERE role='Admin'"))
                conn.execute(text("UPDATE user SET role='Manager' WHERE role='Operator'"))
                conn.execute(text("UPDATE user SET role='Staff' WHERE role='View'"))
        except: pass
        
        db.create_all()
        if not User.query.first():
            admin = User(username='admin', password='password123', role='SuperAdmin', custom_id='USR-ADMIN-001')
            db.session.add(admin)
            db.session.commit()
            
    app.run(debug=True)