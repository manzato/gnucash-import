#!/usr/bin/python

#Took most of the GNUCASH code from http://stackoverflow.com/questions/17055318/create-transaction-in-gnucash-in-response-to-an-email

import argparse
from gnucash import Session, GnuCashBackendException, Account, Transaction, Split, GncNumeric
from datetime import datetime
import json, re, csv
import gnucash
import ConfigParser
from decimal import getcontext, Decimal

def lookup_account_by_path(parent, path):
    try:
      acc = parent.lookup_by_name(path[0])
    except TypeError, e:
      print "Error: %s" % e
      return None

    if acc.get_instance() == None:
        raise Exception('Account path {} not found'.format(':'.join(path)))
    if len(path) > 1:
        return lookup_account_by_path(acc, path[1:])
    return acc

def lookup_account(root, name):
    path = str(name).split(':')
    return lookup_account_by_path(root, path)

def create_transactions(args, conf, url, txs, dry_run):

  try:
    session = Session(url, ignore_lock=True)
  except GnuCashBackendException, backend_exception:
    print "Error: %s" % backend_exception
    exit(1)

  today = datetime.now()
  book = session.book
  root = book.get_root_account()
  currency = book.get_table().lookup('ISO4217', conf.get(args.settings, 'Currency'))

  for tx in txs:
    src_acc = lookup_account(root, tx['src_account'])
    dest_acc = lookup_account(root, tx['dest_account'])

    if src_acc == None:
      print "Couldn't find src account '%s'" % tx['src_account']
      continue

    if dest_acc == None:
      print "Couldn't find dest account '%s'" % tx['dest_account']
      continue

    gtx = Transaction(book)
    gtx.BeginEdit()
    gtx.SetCurrency(currency)
    gtx.SetDateEnteredTS(today)
    gtx.SetDatePostedTS(tx['date']) # or another datetime object for the transaction's "register date"
    gtx.SetDescription(str(tx['label']))

    amount = tx['amount'] * 100

    sp1 = Split(book) # First half of transaction
    sp1.SetParent(gtx)

    # The lookup string needs to match your account path exactly.
    sp1.SetAccount(dest_acc)
    # amount is an int (no $ or .), so $5.23 becomes amount=523
    sp1.SetValue(GncNumeric(amount, 100)) # Assuming you only have one split
    # For multiple splits, you need to make sure the totals all balance out.
    sp1.SetAmount(GncNumeric(amount, 100))
    sp1.SetMemo(str(tx['label'] + ' - Destiny'))

    sp2 = Split(book) # Need a balancing split
    sp2.SetParent(gtx)
    sp2.SetAccount(src_acc)
    sp2.SetValue(sp1.GetValue().neg())
    sp2.SetAmount(sp1.GetValue().neg())
    sp2.SetMemo(str(tx['label'] + ' - Source'))

    gtx.CommitEdit() # Finish editing transaction

  session.save()

  session.end()
  session.destroy()


argsParser = argparse.ArgumentParser(description='Batch process Gnucash transactions')
argsParser.add_argument('--settings', dest='settings', required=True, help='Name of the settings to use within the configuration file')
args = argsParser.parse_args()

conf = ConfigParser.ConfigParser()
conf.read("sync.conf")

verbose = conf.getboolean("General", "Verbose")

if not conf.has_section(args.settings):
  print "Config file has no section named %s" % args.settings
  exit(2)

db_file = conf.get(args.settings, 'File')
log_file = conf.get(args.settings, 'Log')
rules_file = conf.get(args.settings, 'Rules')
def_src_account = conf.get( args.settings, 'DefaultSrcAccount')
date_col = conf.getint(args.settings, 'DateColumn')
desc_col = conf.getint( args.settings, 'DescColumn')
value_cols = map(int,conf.get( args.settings, 'ValueColumn').split(','))
date_format= conf.get( args.settings, 'DateFormat')
delimiter= conf.get( args.settings, 'FieldSeparator')

if verbose:
  print "Using GNUCASH file '%s'" % db_file
  print "Using tx log '%s'" % log_file
  print "Reading rules from '%s'" % rules_file

with open(rules_file) as f:    
    rules = json.load(f)

for rule in rules:
  if verbose:
    print "Adding rule %s" % rule["name"]

  rule['_r'] = re.compile(rule["regexp"])
  if 'src_account' not in rule:
    rule['src_account'] = def_src_account

txs = []

count = 0
missed = 0
with open('sample.csv', 'rb') as csvfile:
  reader = csv.reader(csvfile, delimiter=delimiter)
  for row in reader:
    count += 1
    match = None
    for rule in rules:
      match = rule['_r'].match(row[desc_col])
      if match == None:
        continue
      
      tx = {}
      tx["label"] = rule["tx_label"]

      for c in value_cols:
        if len(row[c]) > 0:
          tx["amount"] = Decimal(row[c])
          break

      tx["date"] =  datetime.strptime(row[date_col], date_format)
      tx["rule"] = rule
      tx["src_account"] = rule['src_account']
      tx["dest_account"] = rule['dest_account']
      
      txs.append(tx)
      break
    if match == None:
      missed += 1
      #print "No rule matched record '%s'" % row[desc_col]

dry_run = True

create_transactions(args, conf, db_file, txs, dry_run)

print "Total rows read     : %d" % count
print "Total rows processed: %d" % len(txs)
print "Total rows missed   : %d" % missed
