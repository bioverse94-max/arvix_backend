import os
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from api.database import SessionLocal
from api.models import Account, Transaction
from api import alert_service

class TransactionStore:
    def __init__(self, path: str = None):
        # path is kept for compatibility with older tests or usage
        self.path = path

    def append(self, transaction: dict) -> None:
        db = SessionLocal()
        try:
            # Create stub accounts if they don't exist
            sender_id = transaction.get("sender_account_id")
            receiver_id = transaction.get("receiver_account_id")
            
            # Ensure sender exists
            if sender_id and not db.query(Account).filter_by(account_id=sender_id).first():
                sender = Account(account_id=sender_id, is_stub=True)
                db.add(sender)
                
            # Ensure receiver exists (avoid duplicate add if sender == receiver)
            if receiver_id and receiver_id != sender_id and not db.query(Account).filter_by(account_id=receiver_id).first():
                receiver = Account(account_id=receiver_id, is_stub=True)
                db.add(receiver)
            
            # Create transaction record
            # We parse timestamp, handle amount conversion, etc.
            # transaction_schema.json format date-time is ISO format.
            try:
                txn_timestamp = datetime.fromisoformat(transaction["timestamp"].replace("Z", "+00:00"))
            except (ValueError, TypeError):
                txn_timestamp = datetime.utcnow()
                
            db_txn = Transaction(
                transaction_id=transaction["transaction_id"],
                sender_account_id=sender_id,
                receiver_account_id=receiver_id,
                amount=transaction["amount"],
                timestamp=txn_timestamp,
                status=transaction["status"]
            )
            db.add(db_txn)

            # Evaluate for alert generation — if the transaction is flagged
            # as fraudulent, create an alert in the same commit.
            if alert_service.evaluate_transaction(transaction):
                alert_service.create_alert(transaction, db)

            db.commit()
        except IntegrityError:
            db.rollback()
            raise ValueError(f"Duplicate transaction_id: {transaction.get('transaction_id')}")
        except Exception as e:
            db.rollback()
            raise
        finally:
            db.close()

    def count(self) -> int:
        db = SessionLocal()
        try:
            return db.query(Transaction).count()
        finally:
            db.close()
