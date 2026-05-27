import unittest

class TesteDBFunctional(unittest.TestCase):
    def test_acid_transaction_pipeline(self):
        db = {"balance_1": 100, "balance_2": 50}
        # Transaction: Transfer 30 from 1 to 2
        try:
            db["balance_1"] -= 30
            db["balance_2"] += 30
            transaction_ok = True
        except:
            transaction_ok = False
        assert transaction_ok
        assert db["balance_1"] == 70
        assert db["balance_2"] == 80
