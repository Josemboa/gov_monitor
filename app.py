import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func
from flask_wtf.csrf import CSRFProtect

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-for-development')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///govmonitor.db')
# Fix for PostgreSQL URI on some platforms
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize CSRF protection
csrf = CSRFProtect(app)

# Initialize database
db = SQLAlchemy(app)

# Initialize login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    evaluations = db.relationship('Evaluation', backref='author', lazy='dynamic')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    color = db.Column(db.String(7), default="#28a745")  # Default to green
    
    projects = db.relationship('Project', backref='category', lazy='dynamic')


class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False)
    region = db.Column(db.String(64), nullable=False)
    
    projects = db.relationship('Project', backref='location', lazy='dynamic')


class ProjectStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    description = db.Column(db.Text)
    color = db.Column(db.String(7), nullable=False)
    
    projects = db.relationship('Project', backref='status', lazy='dynamic')


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    budget = db.Column(db.Float, nullable=False)
    budget_spent = db.Column(db.Float, default=0.0)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    status_id = db.Column(db.Integer, db.ForeignKey('project_status.id'), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'), nullable=False)
    
    evaluations = db.relationship('Evaluation', backref='project', lazy='dynamic')
    milestones = db.relationship('Milestone', backref='project', lazy='dynamic')
    
    @property
    def is_over_budget(self):
        return self.budget_spent > self.budget
    
    @property
    def is_deadline_passed(self):
        return datetime.utcnow() > self.end_date and self.status.name != "Concluído"
    
    @property
    def progress_percentage(self):
        completed_milestones = self.milestones.filter_by(is_completed=True).count()
        total_milestones = self.milestones.count()
        if total_milestones == 0:
            return 0
        return (completed_milestones / total_milestones) * 100


class Milestone(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    deadline = db.Column(db.DateTime, nullable=False)
    is_completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)


class Evaluation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rating = db.Column(db.Integer, nullable=False)  # 1-5 rating
    comment = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


# Login manager user loader
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# Routes
@app.route('/')
def index():
    # Get statistics
    active_projects_count = Project.query.join(ProjectStatus).filter(ProjectStatus.name == "Em andamento").count()
    completed_projects_count = Project.query.join(ProjectStatus).filter(ProjectStatus.name == "Concluído").count()
    evaluations_count = Evaluation.query.count()
    
    # Get total budget and spent amount
    budget_stats = db.session.query(
        func.sum(Project.budget).label('total_budget'),
        func.sum(Project.budget_spent).label('total_spent')
    ).first()
    total_budget = budget_stats.total_budget or 0
    total_spent = budget_stats.total_spent or 0
    
    # Get new projects in current month
    current_month = datetime.utcnow().month
    current_year = datetime.utcnow().year
    new_projects_this_month = Project.query.filter(
        func.extract('month', Project.created_at) == current_month,
        func.extract('year', Project.created_at) == current_year
    ).count()
    
    # Get evaluations from last month
    last_month = current_month - 1 if current_month > 1 else 12
    last_month_year = current_year if current_month > 1 else current_year - 1
    evaluations_last_month = Evaluation.query.filter(
        func.extract('month', Evaluation.created_at) == last_month,
        func.extract('year', Evaluation.created_at) == last_month_year
    ).count()
    
    evaluations_this_month = Evaluation.query.filter(
        func.extract('month', Evaluation.created_at) == current_month,
        func.extract('year', Evaluation.created_at) == current_year
    ).count()
    
    evaluation_difference = evaluations_this_month - evaluations_last_month
    
    # Calculate completion rate
    total_projects = active_projects_count + completed_projects_count
    completion_rate = (completed_projects_count / total_projects * 100) if total_projects > 0 else 0
    
    # Get recent projects by category
    categories = Category.query.all()
    recent_projects = {}
    
    for category in categories:
        recent_projects[category.name] = Project.query.filter_by(category_id=category.id).order_by(Project.created_at.desc()).limit(3).all()
    
    # Query the project statuses needed in the template
    expired_status = ProjectStatus.query.filter_by(name='Prazo expirado').first()
    paralyzed_status = ProjectStatus.query.filter_by(name='Paralisado').first()
    not_started_status = ProjectStatus.query.filter_by(name='Não iniciado').first()
    
    return render_template(
        'index.html',
        active_projects=active_projects_count,
        completed_projects=completed_projects_count,
        evaluations_count=evaluations_count,
        total_budget=total_budget,
        total_spent=total_spent,
        new_projects_this_month=new_projects_this_month,
        evaluation_difference=evaluation_difference,
        completion_rate=completion_rate,
        categories=categories,
        recent_projects=recent_projects,
        expired_status=expired_status,
        paralyzed_status=paralyzed_status,
        not_started_status=not_started_status
    )


@app.route('/projects')
def projects():
    category_id = request.args.get('category', type=int)
    status_id = request.args.get('status', type=int)
    
    query = Project.query
    
    if category_id:
        query = query.filter_by(category_id=category_id)
    
    if status_id:
        query = query.filter_by(status_id=status_id)
    
    projects = query.order_by(Project.created_at.desc()).all()
    categories = Category.query.all()
    statuses = ProjectStatus.query.all()
    
    return render_template(
        'projects.html',
        projects=projects,
        categories=categories,
        statuses=statuses,
        selected_category=category_id,
        selected_status=status_id
    )


@app.route('/projects/<int:project_id>')
def project_detail(project_id):
    project = Project.query.get_or_404(project_id)
    milestones = project.milestones.order_by(Milestone.deadline).all()
    evaluations = project.evaluations.order_by(Evaluation.created_at.desc()).all()
    
    return render_template(
        'project_detail.html',
        project=project,
        milestones=milestones,
        evaluations=evaluations
    )


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Check if username or email already exists
        user_exists = User.query.filter(
            (User.username == username) | (User.email == email)
        ).first()
        
        if user_exists:
            flash('Username or email already exists.', 'danger')
            return redirect(url_for('register'))
        
        # Create new user
        user = User(username=username, email=email)
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! You can now log in.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = 'remember' in request.form
        
        user = User.query.filter_by(username=username).first()
        
        if not user or not user.check_password(password):
            flash('Invalid username or password.', 'danger')
            return redirect(url_for('login'))
        
        login_user(user, remember=remember)
        flash('Login successful!', 'success')
        
        next_page = request.args.get('next')
        return redirect(next_page or url_for('index'))
    
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


@app.route('/submit-evaluation/<int:project_id>', methods=['POST'])
@login_required
def submit_evaluation(project_id):
    project = Project.query.get_or_404(project_id)
    
    rating = request.form.get('rating', type=int)
    comment = request.form.get('comment')
    
    if not rating or not 1 <= rating <= 5:
        flash('Please provide a valid rating (1-5).', 'danger')
        return redirect(url_for('project_detail', project_id=project_id))
    
    if not comment:
        flash('Please provide a comment.', 'danger')
        return redirect(url_for('project_detail', project_id=project_id))
    
    evaluation = Evaluation(
        rating=rating,
        comment=comment,
        project_id=project_id,
        user_id=current_user.id
    )
    
    db.session.add(evaluation)
    db.session.commit()
    
    flash('Your evaluation has been submitted.', 'success')
    return redirect(url_for('project_detail', project_id=project_id))


@app.route('/register-project', methods=['GET', 'POST'])
@login_required
def register_project():
    categories = Category.query.all()
    statuses = ProjectStatus.query.all()
    locations = Location.query.all()
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        budget = request.form.get('budget', type=float)
        start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d')
        end_date = datetime.strptime(request.form.get('end_date'), '%Y-%m-%d')
        category_id = request.form.get('category_id', type=int)
        status_id = request.form.get('status_id', type=int)
        location_id = request.form.get('location_id', type=int)
        
        project = Project(
            title=title,
            description=description,
            budget=budget,
            start_date=start_date,
            end_date=end_date,
            category_id=category_id,
            status_id=status_id,
            location_id=location_id
        )
        
        db.session.add(project)
        db.session.commit()
        
        flash('Projeto registrado com sucesso!', 'success')
        return redirect(url_for('project_detail', project_id=project.id))
    
    return render_template(
        'register_project.html',
        categories=categories,
        statuses=statuses,
        locations=locations
    )


@app.route('/add-tete-location')
@login_required
def add_tete_location():
    # Check if Tete already exists
    tete_location = Location.query.filter_by(name='Tete').first()
    
    if not tete_location:
        # Create Tete location
        tete_location = Location(name='Tete', region='Centro')
        db.session.add(tete_location)
        db.session.commit()
        flash('Localização Tete adicionada com sucesso!', 'success')
    else:
        flash('Localização Tete já existe!', 'info')
    
    return redirect(url_for('register_project'))


@app.route('/add-location/<location_name>/<region>')
@login_required
def add_location(location_name, region):
    # Check if location already exists
    location = Location.query.filter_by(name=location_name).first()
    
    if not location:
        # Create new location
        location = Location(name=location_name, region=region)
        db.session.add(location)
        db.session.commit()
        flash(f'Localização {location_name} adicionada com sucesso!', 'success')
    else:
        flash(f'Localização {location_name} já existe!', 'info')
    
    return redirect(url_for('register_project'))


@app.route('/sobre')
def sobre():
    return render_template('sobre.html')


@app.route('/como-funciona')
def como_funciona():
    return render_template('como_funciona.html')


# API endpoints for AJAX requests
@app.route('/api/projects')
def api_projects():
    category_id = request.args.get('category', type=int)
    status_id = request.args.get('status', type=int)
    
    query = Project.query
    
    if category_id:
        query = query.filter_by(category_id=category_id)
    
    if status_id:
        query = query.filter_by(status_id=status_id)
    
    projects = query.order_by(Project.created_at.desc()).all()
    
    result = []
    for project in projects:
        result.append({
            'id': project.id,
            'title': project.title,
            'category': project.category.name,
            'status': project.status.name,
            'budget': project.budget,
            'budget_spent': project.budget_spent,
            'location': project.location.name,
            'start_date': project.start_date.strftime('%Y-%m-%d'),
            'end_date': project.end_date.strftime('%Y-%m-%d'),
            'is_over_budget': project.is_over_budget,
            'is_deadline_passed': project.is_deadline_passed,
            'progress_percentage': project.progress_percentage
        })
    
    return jsonify(result)


# Initialize the database with sample data
def init_db():
    # Create tables
    db.create_all()
    
    # Check if database is already populated
    if Category.query.first() is not None:
        return
    
    # Create default admin user
    admin = User(
        username='admin',
        email='admin@govmonitor.mz',
        is_admin=True
    )
    admin.set_password('admin123')
    db.session.add(admin)
    
    # Create categories
    categories = [
        {'name': 'Saúde', 'color': '#28a745'},
        {'name': 'Educação', 'color': '#17a2b8'},
        {'name': 'Infraestrutura', 'color': '#fd7e14'}
    ]
    
    for cat_data in categories:
        category = Category(**cat_data)
        db.session.add(category)
    
    # Create project statuses
    statuses = [
        {'name': 'Não iniciado', 'color': '#6c757d', 'description': 'Projeto ainda não iniciado'},
        {'name': 'Em andamento', 'color': '#28a745', 'description': 'Projeto em execução'},
        {'name': 'Paralisado', 'color': '#ffc107', 'description': 'Projeto temporariamente paralisado'},
        {'name': 'Concluído', 'color': '#dc3545', 'description': 'Projeto concluído'},
        {'name': 'Prazo expirado', 'color': '#dc3545', 'description': 'Prazo do projeto expirado'}
    ]
    
    for status_data in statuses:
        status = ProjectStatus(**status_data)
        db.session.add(status)
    
    # Create locations
    locations = [
        {'name': 'Maputo', 'region': 'Sul'},
        {'name': 'Inhambane', 'region': 'Sul'},
        {'name': 'Beira', 'region': 'Centro'},
        {'name': 'Tete', 'region': 'Centro'},
        {'name': 'Nampula', 'region': 'Norte'},
        {'name': 'Pemba', 'region': 'Norte'}
    ]
    
    for loc_data in locations:
        location = Location(**loc_data)
        db.session.add(location)
    
    # Commit to get IDs
    db.session.commit()
    
    # Get created objects
    health_cat = Category.query.filter_by(name='Saúde').first()
    education_cat = Category.query.filter_by(name='Educação').first()
    infra_cat = Category.query.filter_by(name='Infraestrutura').first()
    
    in_progress_status = ProjectStatus.query.filter_by(name='Em andamento').first()
    expired_status = ProjectStatus.query.filter_by(name='Prazo expirado').first()
    
    maputo_loc = Location.query.filter_by(name='Maputo').first()
    beira_loc = Location.query.filter_by(name='Beira').first()
    nampula_loc = Location.query.filter_by(name='Nampula').first()
    
    
    
    # Create sample projects
    projects = [
        {
            'title': 'Construção do Hospital Provincial',
            'description': 'Construção do novo hospital provincial com capacidade para 500 leitos.',
            'budget': 450000000.0,  # 450M MT
            'budget_spent': 200000000.0,
            'start_date': datetime(2023, 1, 1),
            'end_date': datetime(2025, 12, 31),
            'category_id': health_cat.id,
            'status_id': in_progress_status.id,
            'location_id': maputo_loc.id
        },
        {
            'title': 'Reforma da Escola Secundária',
            'description': 'Reforma e ampliação da escola secundária para aumentar a capacidade de alunos.',
            'budget': 120000000.0,  # 120M MT
            'budget_spent': 60000000.0,
            'start_date': datetime(2023, 6, 1),
            'end_date': datetime(2024, 12, 31),
            'category_id': education_cat.id,
            'status_id': in_progress_status.id,
            'location_id': beira_loc.id
        },
        {
            'title': 'Ampliação da Estrada Nacional EN1',
            'description': 'Ampliação e melhoramento da Estrada Nacional EN1 no trecho Nampula-Cabo Delgado.',
            'budget': 780000000.0,  # 780M MT
            'budget_spent': 300000000.0,
            'start_date': datetime(2022, 3, 15),
            'end_date': datetime(2024, 3, 15),
            'category_id': infra_cat.id,
            'status_id': expired_status.id,
            'location_id': nampula_loc.id
        }
    ]
    
    for proj_data in projects:
        project = Project(**proj_data)
        db.session.add(project)
    
    db.session.commit()


@app.cli.command('init-db')
def init_db_command():
    """Initialize the database with sample data."""
    init_db()
    print('Database initialized with sample data.')


if __name__ == '__main__':
    # Initialize database on startup
    with app.app_context():
        init_db()
    
    # Enable auto-reload on file changes
    app.run(debug=True, use_reloader=True)