import sqlite3
import traceback
try:
    c = sqlite3.connect('/data/rtjobs.db')
    print('NOTIFIED = 1:', c.execute('SELECT count(*) FROM jobs WHERE notified = 1').fetchone()[0])
    print('NOTIFIED = 0:', c.execute('SELECT count(*) FROM jobs WHERE notified = 0').fetchone()[0])
except Exception as e:
    print(traceback.format_exc())
