# DB_ENGINE=django.db.backends.mysql expects the `MySQLdb` module (mysqlclient).
# PyMySQL is what requirements.txt ships, so register it under that name.
try:
    import pymysql

    pymysql.install_as_MySQLdb()
except ImportError:
    pass
