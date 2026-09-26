"""Configurações do Django para o CRM.

Todos os valores sensíveis vêm do arquivo .env (veja .env.example).
"""

from pathlib import Path

from config.env import Env

BASE_DIR = Path(__file__).resolve().parent.parent
env = Env()

SECRET_KEY = env.str("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", padrao=False)
# "localhost" fica sempre liberado para a verificação de saúde do Docker.
ALLOWED_HOSTS = [*env.list("DJANGO_ALLOWED_HOSTS"), "localhost"]
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "simple_history",
    "contas",
    "clientes",
    "apolices",
    "beneficiarios",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Registra qual usuário fez cada alteração no histórico.
    "simple_history.middleware.HistoryRequestMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env.str("POSTGRES_DB"),
        "USER": env.str("POSTGRES_USER"),
        "PASSWORD": env.str("POSTGRES_PASSWORD"),
        "HOST": env.str("POSTGRES_HOST", padrao="localhost"),
        "PORT": env.str("POSTGRES_PORT", padrao="5432"),
        "CONN_MAX_AGE": 60,
    }
}

# ------------------------------------------------------------------
# Usuários e senhas
# ------------------------------------------------------------------
AUTH_USER_MODEL = "contas.Usuario"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "inicio"
LOGOUT_REDIRECT_URL = "login"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ------------------------------------------------------------------
# Segurança da sessão e do HTTPS
# ------------------------------------------------------------------
SESSION_COOKIE_AGE = 60 * 60 * 10  # 10 horas: um dia de trabalho
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    # A verificação de saúde do Docker é feita por HTTP dentro do servidor.
    SECURE_REDIRECT_EXEMPT = [r"^saude/$"]
    # O Caddy recebe o HTTPS e repassa para o Django.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# A lista de "preload" do HSTS é para sites públicos; o CRM roda só na rede interna.
SILENCED_SYSTEM_CHECKS = ["security.W021"]

# ------------------------------------------------------------------
# Idioma, fuso e arquivos estáticos
# ------------------------------------------------------------------
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Anexos (ex.: DPS) têm dados sensíveis: ficam fora da pasta pública e só são
# entregues por uma tela que exige login. Não existe MEDIA_URL de propósito.
MEDIA_ROOT = env.str("ANEXOS_DIR", padrao=str(BASE_DIR / "media"))
TAMANHO_MAXIMO_ANEXO_MB = 15

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
