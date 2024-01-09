#!/bin/bash
python3 manage.py migrate
if [ "$NBBB_DEBUG" = 'true' ]; then
  echo "STARTING SERVER IN DEBUG MODE! DO NOT USE IN PRODUCTION!"
  export DJANGO_SUPERUSER_EMAIL=admin@example.com
  export DJANGO_SUPERUSER_USERNAME=admin
  export DJANGO_SUPERUSER_PASSWORD=admin
  python3 manage.py createsuperuser --no-input
  exec python3 manage.py runserver 0.0.0.0:80
fi

python3 manage.py collectstatic --noinput

exec gunicorn -b 0.0.0.0:80 nbblackbox.wsgi