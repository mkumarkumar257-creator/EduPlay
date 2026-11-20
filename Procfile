# Procfile — tells hosting platforms how to start the EduPlay web server.
# Used by: PythonAnywhere (reference), Render, Railway, and Heroku-compatible platforms.
# PythonAnywhere uses its own WSGI panel; this file is a standard reference.
web: gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 60
