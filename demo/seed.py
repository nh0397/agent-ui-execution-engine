"""Repeatable synthetic demo records; existing customer edits are preserved."""


def seed_demo_records(db):
    customers, accounts, cards, transactions = [], [], [], []
    cities = ["Cedar Grove", "Maple Harbor", "Pine Valley", "Willow Creek", "Birch Falls"]
    for i in range(1000):
        customer, account, card = f"C-{1000+i}", f"AC-{10000+i}", f"DC-{1000+i}"
        customers.append((customer, f"Demo Member {i+1:04d}", f"{i+1} Synthetic Way", cities[i % len(cities)], f"{40000+i}"))
        accounts.append((account, customer, "Everyday checking" if i % 2 == 0 else "Savings", 25000 + (i * 7919) % 2500000))
        cards.append((card, customer, f"{1000+i}", "Active"))
        for j, (description, amount) in enumerate([("Synthetic payroll", 175000), ("Demo groceries", -6240), ("Sample utilities", -11800), ("Synthetic interest", 350)]):
            transactions.append((f"TX-SEED-{i:04d}-{j}", account, description, amount, f"2026-09-{15+j:02d}"))
    with db() as conn:
        conn.executemany("INSERT INTO customers(id,name,street,city,postal) VALUES (?,?,?,?,?) ON CONFLICT(id) DO NOTHING", customers)
        conn.executemany("INSERT INTO accounts VALUES (?,?,?,?) ON CONFLICT(id) DO NOTHING", accounts)
        conn.executemany("INSERT INTO cards(id,customer,last_four,status) VALUES (?,?,?,?) ON CONFLICT(id) DO NOTHING", cards)
        conn.executemany("INSERT INTO transactions VALUES (?,?,?,?,?) ON CONFLICT(id) DO NOTHING", transactions)
