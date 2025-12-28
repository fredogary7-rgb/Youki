from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import os
from werkzeug.utils import secure_filename
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
import uuid
from datetime import datetime, timedelta
app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = "ma_cle_ultra_secrete"

login_manager = LoginManager()
login_manager.init_app(app)

UPLOAD_FOLDER = "static/vlogs"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
# URL PostgreSQL (Neon)
DATABASE_URL = "postgresql://neondb_owner:npg_NYzc6Ap8gHah@ep-tiny-moon-abgyer8p-pooler.eu-west-2.aws.neon.tech/neondb?sslmode=require"

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Options moteur SQLAlchemy (IMPORTANT)
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,   # Vérifie si la connexion est encore vivante
    "pool_recycle": 280,     # Recycle avant expiration Neon
    "pool_timeout": 20       # Timeout raisonnable
}

db = SQLAlchemy(app)
from sqlalchemy import text
from flask_migrate import Migrate

migrate = Migrate(app, db)
@app.cli.command("add-ref-col")
def add_reference_column():
    """
    Ajoute la colonne `reference` à la table depot si elle n'existe pas.
    Usage: flask --app app.py add-ref-col
    """
    with db.engine.connect() as conn:
        conn.execute(text("""
            ALTER TABLE depot
            ADD COLUMN IF NOT EXISTS reference VARCHAR(200);
        """))
        conn.commit()
    print("✅ Colonne 'reference' ajoutée si elle n'existait pas.")

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)

    # =====================
    # Identifiants
    # =====================
    uid = db.Column(
        db.String(50),
        unique=True,
        nullable=False,
        default=lambda: str(uuid.uuid4())
    )

    phone = db.Column(db.String(30), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)

    # =====================
    # Parrainage
    # =====================
    parrain = db.Column(db.String(30), nullable=True)
    commission_total = db.Column(db.Float, default=0.0)

    # =====================
    # Portefeuille
    # =====================
    wallet_country = db.Column(db.String(50))
    wallet_operator = db.Column(db.String(50))
    wallet_number = db.Column(db.String(30))

    # =====================
    # Soldes
    # =====================
    solde_total = db.Column(db.Float, default=0.0)
    solde_depot = db.Column(db.Float, default=0.0)
    solde_parrainage = db.Column(db.Float, default=0.0)
    solde_revenu = db.Column(db.Float, default=0.0)

    premier_depot = db.Column(db.Boolean, default=False)

    # =====================
    # Lucky Spin
    # =====================
    spin_chances = db.Column(db.Integer, default=1)
    last_spin_gain = db.Column(db.Float, default=0.0)

    # =====================
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

class Depot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(30))
    montant = db.Column(db.Float)
    reference = db.Column(db.String(200), nullable=True)
    statut = db.Column(db.String(20), default="en_attente")  #  NEW
    date = db.Column(db.DateTime, default=datetime.utcnow)


class Investissement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(30))
    montant = db.Column(db.Float)
    revenu_journalier = db.Column(db.Float)
    duree = db.Column(db.Integer)
    date_debut = db.Column(db.DateTime, default=datetime.utcnow)
    dernier_paiement = db.Column(db.DateTime, default=datetime.utcnow)   # 🔥 OBLIGATOIRE
    actif = db.Column(db.Boolean, default=True)

class Retrait(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(30))
    montant = db.Column(db.Float)
    statut = db.Column(db.String(20), default="en_attente")
    date = db.Column(db.DateTime, default=datetime.utcnow)

class Staking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(30), nullable=False)
    vip_level = db.Column(db.String(20), nullable=False)
    montant = db.Column(db.Float, nullable=False)
    duree = db.Column(db.Integer, default=15)
    taux_min = db.Column(db.Float, default=1.80)
    taux_max = db.Column(db.Float, default=2.20)
    revenu_total = db.Column(db.Float, nullable=False)
    date_debut = db.Column(db.DateTime, default=datetime.utcnow)
    actif = db.Column(db.Boolean, default=True)

class Commission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    parrain_phone = db.Column(db.String(30))    # celui qui gagne
    filleul_phone = db.Column(db.String(30))    # celui qui a fait l'action
    montant = db.Column(db.Float)
    niveau = db.Column(db.Integer)              # 1, 2 ou 3
    date = db.Column(db.DateTime, default=datetime.utcnow)

class Vlog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(30))
    montant = db.Column(db.Float)
    image = db.Column(db.String(200))
    statut = db.Column(db.String(20), default="en_attente") # en_attente / valide / rejete
    date = db.Column(db.DateTime, default=datetime.utcnow)

def donner_commission(filleul_phone, montant):
    # Niveaux : 30% – 5% – 3%
    COMMISSIONS = {1: 0.20, 2: 0.03, 3: 0.01}

    current_phone = filleul_phone

    for niveau in range(1, 4):
        user = User.query.filter_by(phone=current_phone).first()

        # si pas de parrain → stop
        if not user or not user.parrain:
            break

        parrain = User.query.filter_by(phone=user.parrain).first()
        if not parrain:
            break

        gain = montant * COMMISSIONS[niveau]

        commission = Commission(
            parrain_phone=parrain.phone,
            filleul_phone=filleul_phone,
            montant=gain,
            niveau=niveau
        )
        db.session.add(commission)

        parrain.solde_parrainage += gain
        parrain.commission_total += gain

        db.session.commit()

        current_phone = parrain.phone

def t(key):
    lang = session.get("lang", "fr")
    return TRANSLATIONS.get(lang, TRANSLATIONS["fr"]).get(key, key)

app.jinja_env.globals.update(t=t)

def get_logged_in_user_phone():
    phone = session.get("phone")
    if not phone:
        return None
    return str(phone).strip()

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not get_logged_in_user_phone():
            return redirect(url_for("connexion_page"))
        return f(*args, **kwargs)
    return wrapper


def verifier_investissements(phone):
    """Vérifie si les investissements d'un user sont terminés et crédite les gains."""
    investissements = Investissement.query.filter_by(phone=phone, actif=True).all()

    for inv in investissements:
        date_fin = inv.date_debut + timedelta(days=inv.duree)

        if datetime.utcnow() >= date_fin:
            revenu_total = inv.revenu_journalier * inv.duree

            user = User.query.filter_by(phone=phone).first()
            user.solde_revenu += revenu_total

            user.solde_total += inv.montant

            inv.actif = False

            db.session.commit()


import random

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
# --------------------------
# Fonction de tirage pondéré
# --------------------------
def weighted_choice():
    gains = [
        (3000, 10),
        (5400, 7),
        (7200, 6),
        (12000, 5),
        (22800, 4),
        (52800, 1.5),
        (112800, 1),
        (532800, 0.1)
    ]

    pool = []
    for gain, weight in gains:
        pool.extend([gain] * int(weight * 10))
    return random.choice(pool)


@app.cli.command("init-db")
def init_db():
    db.create_all()
    print("✅ Base de données initialisée avec succès !")

@app.route("/inscription", methods=["GET", "POST"])
def inscription_page():

    # 🔥 Récupère le code ref dans l'URL si présent
    code_ref = request.args.get("ref", "").strip()

    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip()
        confirm = request.form.get("confirm_password", "").strip()
        code_invitation = request.form.get("code_invitation", "").strip()

        if not phone or not password:
            flash("⚠️ Tous les champs obligatoires doivent être remplis.", "danger")
            return redirect(url_for("inscription_page"))

        if password != confirm:
            flash("❌ Les mots de passe ne correspondent pas.", "danger")
            return redirect(url_for("inscription_page"))

        if User.query.filter_by(phone=phone).first():
            flash("⚠️ Ce numéro est déjà enregistré.", "danger")
            return redirect(url_for("inscription_page"))

        parrain_user = None
        if code_invitation:
            parrain_user = User.query.filter_by(phone=code_invitation).first()
            if not parrain_user:
                flash("⚠️ Code d'invitation invalide.", "warning")

        new_user = User(
            phone=phone,
            password=password,
            solde_total=0,
            solde_depot=0,
            solde_revenu=0,
            solde_parrainage=0,
            parrain=parrain_user.phone if parrain_user else None
        )

        db.session.add(new_user)
        db.session.commit()

        flash("🎉 Inscription réussie ! Connectez-vous maintenant.", "success")
        return redirect(url_for("connexion_page"))

    # 🔥 Passe le code au HTML
    return render_template("inscription.html", code_ref=code_ref)

from flask_login import login_user

@app.route("/connexion", methods=["GET", "POST"])
def connexion_page():
    if request.method == "POST":

        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip()

        if not phone or not password:
            flash("⚠️ Veuillez remplir tous les champs.", "danger")
            return redirect(url_for("connexion_page"))

        user = User.query.filter_by(phone=phone).first()

        if not user:
            flash("❌ Numéro introuvable.", "danger")
            return redirect(url_for("connexion_page"))

        if user.password != password:
            flash("❌ Mot de passe incorrect.", "danger")
            return redirect(url_for("connexion_page"))

        # ✅ CONNEXION FLASK-LOGIN
        login_user(user)

        flash("Connexion réussie ✅", "success")
        return redirect(url_for("dashboard_page"))

    return render_template("connexion.html")

@app.route("/logout")
def logout_page():
    session.clear()
    flash("Déconnexion effectuée.", "info")
    return redirect(url_for("connexion_page"))

PRODUITS_VIP = [
    {"id": 1, "nom": "VIP 1", "prix": 3000, "revenu_journalier": 500, "image": "you3.jpg"},
    {"id": 2, "nom": "VIP 2", "prix": 8000, "revenu_journalier": 1350, "image": "you3.jpg"},
    {"id": 3, "nom": "VIP 3", "prix": 20000, "revenu_journalier": 3650, "image": "you.jpg"},
    {"id": 4, "nom": "VIP 4", "prix": 40000, "revenu_journalier": 8000, "image": "you.jpg"},
    {"id": 5, "nom": "VIP 5", "prix": 90000, "revenu_journalier": 20000, "image": "you.jpg"},
    {"id": 6, "nom": "VIP 6", "prix": 180000, "revenu_journalier": 42000, "image": "you.jpg"},
    {"id": 7, "nom": "VIP 7", "prix": 400000, "revenu_journalier": 100000, "image": "you.jpg"},
    {"id": 8, "nom": "VIP 8", "prix": 800000, "revenu_journalier": 220000, "image": "you.jpg"}
]

@app.route("/produits_rapide")
@login_required
def produits_rapide_page():
    phone = get_logged_in_user_phone()
    user = User.query.filter_by(phone=phone).first()

    max_invest = db.session.query(db.func.max(Investissement.montant)) \
        .filter_by(phone=phone, actif=True).scalar() or 0

    return render_template(
        "produits_rapide.html",
        user=user,
        produits=PRODUITS_VIP,
        max_invest=max_invest
    )

@app.route("/produits_rapide/valider/<int:vip_id>", methods=["POST"])
@login_required
def valider_produit_rapide(vip_id):
    phone = get_logged_in_user_phone()
    user = User.query.filter_by(phone=phone).first()

    produit = next((p for p in PRODUITS_VIP if p["id"] == vip_id), None)
    if not produit:
        flash("Produit introuvable.", "danger")
        return redirect(url_for("produits_rapide_page"))

    montant = produit["prix"]

    if user.solde_total < montant:
        flash("Solde insuffisant.", "danger")
        return redirect(url_for("produits_rapide_page"))

    # Enregistrer
    inv = Investissement(
        phone=phone,
        montant=montant,
        revenu_journalier=produit["revenu_journalier"],
        duree=60,
        actif=True
    )
    db.session.add(inv)

    # Débiter le solde
    user.solde_total -= montant
    db.session.commit()

    # Page spéciale avec chargement + succès
    return render_template("achat_rapide_loader.html", produit=produit)

@app.route("/produits_rapide/confirmer/<int:vip_id>", methods=["GET", "POST"])
@login_required
def confirmer_produit_rapide(vip_id):
    phone = get_logged_in_user_phone()
    user = User.query.filter_by(phone=phone).first()

    produit = next((p for p in PRODUITS_VIP if p["id"] == vip_id), None)
    if not produit:
        flash("Produit introuvable.", "danger")
        return redirect(url_for("produits_rapide_page"))

    montant = produit["prix"]
    revenu_journalier = produit["revenu_journalier"]
    revenu_total = revenu_journalier * 60

    # GET → afficher page
    if request.method == "GET":
        return render_template(
            "confirm_rapide.html",
            p=produit,
            revenu_total=revenu_total,
            user=user
        )

    # POST → CONFIRMER ACHAT
    if float(user.solde_total or 0) < montant:
        flash("Solde insuffisant.", "danger")
        return redirect(url_for("produits_rapide_page"))

    # 🔥 Débit du VRAI solde utilisé dans ton dashboard
    user.solde_total -= montant

    # 🔥 Création investissement
    inv = Investissement(
        phone=phone,
        montant=montant,
        revenu_journalier=revenu_journalier,
        duree=60,
        actif=True
    )
    db.session.add(inv)

    db.session.commit()

    return render_template(
        "confirm_rapide_loading.html",
        montant=montant,
        produit=produit
    )

def get_global_stats():
    total_users = db.session.query(func.count(User.id)).scalar() or 0
    total_deposits = db.session.query(func.sum(Depot.montant)).scalar() or 0
    total_invested = db.session.query(func.sum(Investissement.montant)).scalar() or 0
    total_withdrawn = db.session.query(func.sum(Retrait.montant)).scalar() or 0

    return total_users, total_deposits, total_invested, total_withdrawn

@app.route("/dashboard")
@login_required
def dashboard_page():
    phone = get_logged_in_user_phone()
    user = User.query.filter_by(phone=phone).first()

    if not user:
        session.clear()
        flash("Session invalide, veuillez vous reconnecter.", "danger")
        return redirect(url_for("connexion_page"))

    total_users, total_deposits, total_invested, total_withdrawn = get_global_stats()

    # 🔥 Revenu cumulé = commissions + revenus investissements
    revenu_cumule = (user.solde_parrainage or 0) + (user.solde_revenu or 0)

    return render_template(
        "dashboard.html",
        user=user,
        revenu_cumule=revenu_cumule,  # 🔥 envoi au HTML
        total_users=total_users,
        total_invested=total_invested,
    )

@app.route("/historique")
@login_required
def historique_page():
    phone = get_logged_in_user_phone()

    # 🔹 Dépôts
    depots = Depot.query.filter_by(phone=phone).order_by(Depot.date.desc()).all()

    # 🔹 Retraits
    retraits = Retrait.query.filter_by(phone=phone).order_by(Retrait.date.desc()).all()

    # 🔹 Revenus (investissements)
    investissements = []
    now = datetime.now()

    for inv in Investissement.query.filter_by(phone=phone).all():
        jours_passes = (now - inv.date_debut).days
        progression = min(int((jours_passes / inv.duree) * 100), 100)
        jours_restants = max(inv.duree - jours_passes, 0)

        investissements.append({
            "montant": inv.revenu_journalier,
            "jours_restants": jours_restants,
            "progression": progression
        })

    return render_template(
        "historique.html",
        depots=depots,
        retraits=retraits,
        investissements=investissements
    )

@app.route("/deposit", methods=["GET", "POST"])
@login_required
def deposit_page():
    phone = get_logged_in_user_phone()
    user = User.query.filter_by(phone=phone).first()

    if request.method == "POST":
        montant = float(request.form["montant"])
        reference = request.form["reference"]

        depot = Depot(
            phone=phone,
            montant=montant,
            reference=reference
        )
        db.session.add(depot)
        db.session.commit()

        flash("Dépôt soumis avec succès !", "success")
        return redirect(url_for("dashboard_page"))

    return render_template("deposit.html", user=user)

@app.route("/submit_reference", methods=["POST"])
@login_required
def submit_reference():
    phone = get_logged_in_user_phone()
    montant = float(request.form["montant"])
    reference = request.form["reference"]

    depot = Depot(
        phone=phone,
        montant=montant,
        reference=reference
    )
    db.session.add(depot)
    db.session.commit()

    # 👉 au lieu de redirect, on affiche une page avec loader + succès
    return render_template(
        "submit_reference_loading.html",
        montant=montant,
        reference=reference
    )

@app.route("/ajouter_portefeuille", methods=["GET", "POST"])
@login_required
def wallet_setup_page():
    phone = get_logged_in_user_phone()
    user = User.query.filter_by(phone=phone).first()

    if not user:
        flash("Session expirée, reconnectez-vous.", "danger")
        return redirect(url_for("connexion_page"))

    if user.wallet_number:
        return redirect(url_for("retrait_page"))

    if request.method == "POST":
        country = request.form["country"]
        operator = request.form["operator"]
        number = request.form["number"]

        user.wallet_country = country
        user.wallet_operator = operator
        user.wallet_number = number
        db.session.commit()

        flash("Compte de retrait enregistré avec succès.", "success")
        return redirect(url_for("retrait_page"))

    return render_template("wallet_setup.html")

@app.route("/retrait", methods=["GET", "POST"])
@login_required
def retrait_page():
    phone = get_logged_in_user_phone()
    user = User.query.filter_by(phone=phone).first()

    if not user:
        flash("Session invalide.", "danger")
        return redirect(url_for("connexion_page"))

    # Le user doit avoir configuré son portefeuille
    if not user.wallet_number:
        return redirect(url_for("wallet_setup_page"))

    # ✅ Solde retirable = Parrainage + Revenus
    solde_retraitable = (user.solde_parrainage or 0) + (user.solde_revenu or 0)

    if request.method == "POST":
        try:
            montant = float(request.form["montant"])
        except:
            flash("Montant invalide.", "danger")
            return redirect(url_for("retrait_page"))

        if montant < 1000:
            flash("Montant minimum : 1000 XOF.", "warning")
            return redirect(url_for("retrait_page"))

        if montant > solde_retraitable:
            flash("Solde insuffisant.", "danger")
            return redirect(url_for("retrait_page"))

        return redirect(url_for("retrait_confirmation_page", montant=montant))

    return render_template(
        "retrait.html",
        user=user,
        solde_total=user.solde_total,
        solde_retraitable=solde_retraitable
    )


@app.route("/retrait/confirmation/<int:montant>", methods=["GET", "POST"])
@login_required
def retrait_confirmation_page(montant):
    phone = get_logged_in_user_phone()
    user = User.query.filter_by(phone=phone).first()

    if not user:
        flash("Session expirée.", "danger")
        return redirect(url_for("connexion_page"))

    # Vérification des fonds
    solde_retraitable = (user.solde_parrainage or 0) + (user.solde_revenu or 0)
    if montant > solde_retraitable:
        flash("Solde insuffisant.", "danger")
        return redirect(url_for("retrait_page"))

    # Calcul taxe et montant net
    taxe = int(montant * 0.15)
    net = montant - taxe

    # Si l'utilisateur clique sur "Confirmer"
    if request.method == "POST":

        retrait = Retrait(
            phone=phone,
            montant=montant,
            statut="en_attente"
        )
        db.session.add(retrait)

        # Déduction du solde
        reste = montant

        if user.solde_parrainage >= reste:
            user.solde_parrainage -= reste
            reste = 0
        else:
            reste -= user.solde_parrainage
            user.solde_parrainage = 0

        if reste > 0:
            user.solde_revenu -= reste


        db.session.commit()

        # 👉 On renvoie une page spéciale avec chargement + succès + redirection
        return render_template(
            "retrait_confirmation_loading.html",
            montant=montant,
            taxe=taxe,
            net=net,
            user=user
        )

    # GET → afficher la page de confirmation normale
    return render_template(
        "retrait_confirmation.html",
        montant=montant,
        taxe=taxe,
        net=net,
        user=user
    )

from flask_login import login_required, current_user
from flask import request, render_template, flash

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.route("/lucky-spin", methods=["GET", "POST"])
@login_required
def lucky_spin():

    # Sécurisation des valeurs
    if current_user.spin_chances is None:
        current_user.spin_chances = 1

    if current_user.solde_total is None:
        current_user.solde_total = 0

    if current_user.solde_revenu is None:
        current_user.solde_revenu = 0

    # Déjà joué
    if current_user.spin_chances <= 0:
        db.session.commit()
        flash("❌ Vous avez déjà participé au Lucky Spin", "danger")
        return render_template("lucky_spin.html", blocked=True)

    # Action POST (spin)
    if request.method == "POST":
        gain = weighted_choice()

        current_user.solde_revenu += gain
        current_user.spin_chances = 0

        db.session.commit()

        flash(f"🎉 Félicitations ! Vous avez gagné {gain} XOF", "success")
        return render_template(
            "lucky_spin.html",
            result=gain,
            blocked=True
        )

    # GET normal
    db.session.commit()
    return render_template("lucky_spin.html", blocked=False)

@app.route("/profile")
@login_required
def profile_page():
    phone = get_logged_in_user_phone()
    user = User.query.filter_by(phone=phone).first()

    return render_template("profile.html", user=user)

def get_image(montant):
    mapping = {
        3000: "cyber1.jpg",
        8000: "cyber2.jpg",
        20000: "cyber3.jpg",
        40000: "cyber4.jpg",
        90000: "cyber5.jpg",
        180000: "cyber6.jpg",
        400000: "cyber7.jpg",
        800000: "cyber8.jpg",
    }
    return mapping.get(int(montant), "cyber1.jpg")

@app.route("/historique")
@login_required
def historique_invest_page():
    phone = get_logged_in_user_phone()

    investissements = []

    now = datetime.now()   # 👍 PAS DE WARNING

    for inv in Investissement.query.filter_by(phone=phone).all():

        jours_passes = (now - inv.date_debut).days
        progression = int((jours_passes / inv.duree) * 100)
        progression = min(progression, 100)
        jours_restants = max(inv.duree - jours_passes, 0)

        investissements.append({
            "nom": f"prix {inv.montant}",
            "revenu_journalier": inv.revenu_journalier,
            "jours_restants": jours_restants,
            "progression": progression,
            "image": get_image(inv.montant)
        })

    return render_template("historique_invest.html",
                           investissements=investissements)

@app.route('/team')
@login_required
def team_page():
    phone = get_logged_in_user_phone()
    user = User.query.filter_by(phone=phone).first()

    referral_code = phone
    referral_link = url_for('inscription_page', _external=True) + f'?ref={referral_code}'

    from sqlalchemy import func

    # ----- NIVEAU 1 -----
    level1_users = User.query.filter_by(parrain=referral_code).all()
    level1_phones = [u.phone for u in level1_users]
    level1_count = len(level1_users)

    # ----- NIVEAU 2 -----
    if level1_phones:
        level2_users = User.query.filter(User.parrain.in_(level1_phones)).all()
        level2_phones = [u.phone for u in level2_users]
        level2_count = len(level2_users)
    else:
        level2_users = []
        level2_phones = []
        level2_count = 0

    # ----- NIVEAU 3 -----
    if level2_phones:
        level3_users = User.query.filter(User.parrain.in_(level2_phones)).all()
        level3_phones = [u.phone for u in level3_users]
        level3_count = len(level3_users)
    else:
        level3_users = []
        level3_phones = []
        level3_count = 0

    # ----- COMMISSIONS -----
    commissions_total = float(user.solde_parrainage or 0)

    # ----- DÉPÔTS DE LA TEAM (NIVEAU 1 + 2 + 3) -----
    all_team_phones = level1_phones + level2_phones + level3_phones

    if all_team_phones:
        team_deposits = float(
            db.session.query(func.coalesce(func.sum(Depot.montant), 0))
            .filter(Depot.phone.in_(all_team_phones))
            .scalar()
        )
    else:
        team_deposits = 0.0

    # ----- STATISTIQUES -----
    stats = {
        "level1": level1_count,
        "level2": level2_count,
        "level3": level3_count,
        "commissions_total": commissions_total,
        "team_deposits": team_deposits
    }

    return render_template(
        "team.html",
        referral_code=referral_code,
        referral_link=referral_link,
        stats=stats
    )

@app.route("/admin/deposits")
def admin_deposits():
    depots = Depot.query.order_by(Depot.date.desc()).all()
    return render_template("admin_deposits.html", depots=depots)


@app.route("/admin/deposits/valider/<int:depot_id>")
def valider_depot(depot_id):
    depot = Depot.query.get_or_404(depot_id)
    user = User.query.filter_by(phone=depot.phone).first()

    if not user:
        flash("Utilisateur introuvable.", "danger")
        return redirect("/admin/deposits")

    if hasattr(depot, "statut") and depot.statut == "valide":
        flash("Ce dépôt est déjà validé.", "warning")
        return redirect("/admin/deposits")

    # 🔥 VÉRIFIER SI C'EST SON PREMIER DÉPÔT VALIDÉ
    premier_depot = Depot.query.filter_by(phone=user.phone, statut="valide").first()

    # 🔥 Créditer le dépôt
    user.solde_depot += depot.montant
    user.solde_total += depot.montant
    depot.statut = "valide"

    # 🔥 SI C’EST SON PREMIER DÉPÔT → COMMISSIONS
    if not premier_depot and user.parrain:
        donner_commission(user.phone, depot.montant)

    db.session.commit()

    flash("Dépôt validé et crédité avec succès !", "success")
    return redirect("/admin/deposits")

@app.route("/admin/deposits/rejeter/<int:depot_id>")
def rejeter_depot(depot_id):
    depot = Depot.query.get_or_404(depot_id)

    # Si déjà traité
    if hasattr(depot, "statut") and depot.statut in ["valide", "rejete"]:
        flash("Ce dépôt a déjà été traité.", "warning")
        return redirect("/admin/deposits")

    depot.statut = "rejete"
    db.session.commit()

    flash("Dépôt rejeté avec succès.", "danger")
    return redirect("/admin/deposits")


@app.route("/admin/retraits")
def admin_retraits():
    retraits = Retrait.query.order_by(Retrait.date.desc()).all()
    return render_template("admin_retraits.html", retraits=retraits)

@app.route("/admin/retraits/valider/<int:retrait_id>")
def valider_retrait(retrait_id):
    retrait = Retrait.query.get_or_404(retrait_id)

    if retrait.statut == "validé":
        flash("Ce retrait est déjà validé.", "info")
        return redirect("/admin/retraits")

    retrait.statut = "validé"
    db.session.commit()

    flash("Retrait validé avec succès !", "success")
    return redirect("/admin/retraits")

@app.route("/admin/retraits/refuser/<int:retrait_id>")
def refuser_retrait(retrait_id):
    retrait = Retrait.query.get_or_404(retrait_id)
    user = User.query.filter_by(phone=retrait.phone).first()

    if retrait.statut == "refusé":
        return redirect("/admin/retraits")

    montant = retrait.montant

    user.solde_revenu += montant
    retrait.statut = "refusé"
    db.session.commit()

    flash("Retrait refusé et montant recrédité à l’utilisateur.", "warning")
    return redirect("/admin/retraits")

@app.route("/finance")
@login_required
def finance_page():
    phone = get_logged_in_user_phone()
    user = User.query.filter_by(phone=phone).first()

    if not user:
        flash("Session expirée.", "danger")
        return redirect(url_for("connexion_page"))

    revenus_totaux = (user.solde_revenu or 0) + (user.solde_parrainage or 0)
    fortune_totale = (user.solde_depot or 0) + revenus_totaux

    # 🔹 RETRAITS
    retraits = Retrait.query.filter_by(phone=phone)\
        .order_by(Retrait.date.desc()).limit(10).all()

    # 🔹 DEPOTS (NOUVEAU)
    depots = Depot.query.filter_by(phone=phone)\
        .order_by(Depot.date.desc()).limit(10).all()

    # 🔹 INVESTISSEMENTS ACTIFS
    actifs_raw = Investissement.query.filter_by(phone=phone, actif=True).all()

    actifs = []
    for a in actifs_raw:
        date_fin = a.date_debut + timedelta(days=a.duree)
        actifs.append({
            "montant": a.montant,
            "revenu_journalier": a.revenu_journalier,
            "duree": a.duree,
            "date_debut": a.date_debut,
            "date_fin": date_fin
        })

    return render_template(
        "finance.html",
        user=user,
        revenus_totaux=revenus_totaux,
        fortune_totale=fortune_totale,
        retraits=retraits,
        depots=depots,     # 🔥 envoyé au template
        actifs=actifs
    )

@app.route("/cron/pay_invests")
def cron_pay_invests():
    maintenant = datetime.utcnow()
    invests = Investissement.query.filter_by(actif=True).all()

    total_payes = 0

    for inv in invests:
        # Protéger si dernier_paiement manquant
        if not inv.dernier_paiement:
            inv.dernier_paiement = inv.date_debut

        diff = maintenant - inv.dernier_paiement

        # 🔥 Si 24h sont passées → créditer le revenu
        if diff.total_seconds() >= 86400:

            user = User.query.filter_by(phone=inv.phone).first()
            if user:
                user.solde_revenu += inv.revenu_journalier
                total_payes += 1

            inv.dernier_paiement = maintenant

            # Incrémenter la durée restante
            inv.duree -= 1
            if inv.duree <= 0:
                inv.actif = False

    db.session.commit()
    return f"{total_payes} paiements effectués."

import threading
import time
from datetime import datetime, timedelta

def paiement_quotidien():
    while True:
        time.sleep(60)  # vérifie toutes les 60 secondes

        with app.app_context():  # 🔥 OBLIGATOIRE pour éviter l’erreur "Working outside application context"

            investissements = Investissement.query.filter_by(actif=True).all()

            for inv in investissements:
                now = datetime.utcnow()

                # Si jamais la colonne est vide
                if not inv.dernier_paiement:
                    inv.dernier_paiement = inv.date_debut

                # Vérifie si 24h sont passées
                if now - inv.dernier_paiement >= timedelta(hours=24):

                    user = User.query.filter_by(phone=inv.phone).first()
                    if not user:
                        continue

                    # 🔥 Crédit du revenu
                    user.solde_revenu = float(user.solde_revenu or 0) + inv.revenu_journalier
                    user.solde_total = float(user.solde_total or 0) + inv.revenu_journalier

                    # Met à jour la date du dernier paiement
                    inv.dernier_paiement = now

                    # Réduit la durée restante
                    inv.duree -= 1
                    if inv.duree <= 0:
                        inv.actif = False

                    db.session.commit()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")


