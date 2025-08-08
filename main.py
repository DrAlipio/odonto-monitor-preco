from fastapi import FastAPI
import csv
import os

app = FastAPI()

CSV_FILE = "compras.csv"

# Criar o arquivo CSV se não existir
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["Produto", "Marca", "Modelo", "Fornecedor", "Preço"])

@app.post("/adicionar_compra/")
def adicionar_compra(produto: str, marca: str, modelo: str, fornecedor: str, preco: float):
    with open(CSV_FILE, mode="a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([produto, marca, modelo, fornecedor, preco])
    return {"mensagem": "Compra adicionada com sucesso"}

@app.get("/listar_compras/")
def listar_compras():
    with open(CSV_FILE, mode="r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return list(reader)
