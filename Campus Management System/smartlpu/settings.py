import os

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


SECRET_KEY = os.environ.get(
    "SMARTLPU_SECRET_KEY",
    os.environ.get(
        "CMS_SECRET_KEY",
        "django-insecure-+@7t79ho(s0v$ah_-1g-_lw-lu-h@k$(*s+6%kxh90opo7m&v#",
    ),
)

DEBUG = (os.environ.get("SMARTLPU_DEBUG", os.environ.get("CMS_DEBUG", "1")) == "1")

_hosts_raw = os.environ.get("SMARTLPU_ALLOWED_HOSTS", os.environ.get("CMS_ALLOWED_HOSTS", ""))
ALLOWED_HOSTS = [h.strip() for h in _hosts_raw.split(",") if h.strip()] if _hosts_raw else []


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'accounts',
    'blocks',
    'classrooms',
    'courses',
    'faculty',
    'analytics',
    'attendance',
    'food_ordering',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'smartlpu.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'smartlpu.context_processors.rbac_flags',
            ],
        },
    },
]

WSGI_APPLICATION = 'smartlpu.wsgi.application'


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Kolkata'

USE_I18N = True

USE_TZ = True


STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('SMARTLPU_EMAIL_HOST_USER', os.environ.get('CMS_EMAIL_HOST_USER', ''))
EMAIL_HOST_PASSWORD = os.environ.get('SMARTLPU_EMAIL_HOST_PASSWORD', os.environ.get('CMS_EMAIL_HOST_PASSWORD', ''))
DEFAULT_FROM_EMAIL = os.environ.get(
    'SMARTLPU_DEFAULT_FROM_EMAIL',
    os.environ.get('CMS_DEFAULT_FROM_EMAIL', EMAIL_HOST_USER),
)
EMAIL_TIMEOUT = 10

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
