return {"baixas": baixas}

# --- NOVO CÓDIGO ---
@app.post("/registrar_compra")
def registrar_compra(payload: dict):
    """
    Registra uma compra no CSV local.
    Espera receber: url (str) e preco_pago (float)
    """
    import csv, os
    from datetime import datetime

    arquivo_csv = "compras.csv"
    campos = ["data", "url", "preco_pago"]

    # Se o arquivo não existir, cria com cabeçalho
    if not os.path.exists(arquivo_csv):
        with open(arquivo_csv, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=campos)
            writer.writeheader()

    # Adiciona a nova linha
    with open(arquivo_csv, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writerow({
            "data": datetime.utcnow().strftime("%Y-%m-%d"),
            "url": payload["url"],
            "preco_pago": payload["preco_pago"]
        })

    return {"mensagem": "Compra registrada com sucesso!"}
