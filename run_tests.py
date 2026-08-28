import sys
from tests.test_api_ingestion import (
    test_valid_transaction_is_stored,
    test_sender_receiver_account_relationship_works,
    test_duplicate_txn_id_is_rejected,
    test_invalid_transaction_is_not_stored,
    test_self_transfer_same_sender_receiver
)
from api.database import SessionLocal
from api.models import Transaction, Account

def clean_db():
    db = SessionLocal()
    db.query(Transaction).delete()
    db.query(Account).delete()
    db.commit()
    db.close()

def run():
    tests = [
        test_valid_transaction_is_stored,
        test_sender_receiver_account_relationship_works,
        test_duplicate_txn_id_is_rejected,
        test_invalid_transaction_is_not_stored,
        test_self_transfer_same_sender_receiver
    ]
    
    passed = 0
    for test in tests:
        clean_db()
        try:
            print(f"Running {test.__name__}...", end=" ")
            test()
            print("OK")
            passed += 1
        except Exception as e:
            print(f"FAILED: {e}")
            import traceback
            traceback.print_exc()
                
    print(f"\n{passed}/{len(tests)} tests passed.")
    if passed < len(tests):
        sys.exit(1)

if __name__ == "__main__":
    run()
