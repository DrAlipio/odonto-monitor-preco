# main.py — Odonto Compras (OCR + Preços + Registro + Relatórios)
from __future__ import annotations

# ----------------- Imports base -----------------
import os, re
from datetime import date, datetime
from typing import List, Optional, Literal, Dict, Any

import requests
from bs4 import BeautifulSoup

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel, Field
from dotenv import load_dotenv

# ----------------- Banco de dados -----------------
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Date, func
)
from sqlalchemy.orm import declarative_base, sessionmaker

# .env é útil localmente; no Render vale a var de ambiente
load_dotenv()
DATABASE_URL = (
    os.getenv("DATABASE_URL")
    or os.getenv("database_url")
    or os.getenv("Database_Url")
)
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL não definida (Render > Settings > Environment).")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ----------------- Categorização -----------------
CATEGORIAS_MAP = {
    "lima": "Endodontia",
    "k-file": "Endodontia",
    "hedstroem": "Endodontia",
    "guta": "Endodontia",
    "cone": "Endodontia",
    "algodão": "Básico",
    "gaze": "Básico",
    "luva": "Básico",
    "mascara": "Básico",
    "máscara": "Básico",
    "escova": "Higiene",
    "fio dental": "Higiene",
    "anest": "Anestesia",
}

def inferir_categoria(nome: str) -> str:
    n = (nome or "").lower()
    for chave, cat in CATEGORIAS_MAP.items():
        if chave in n:
            return cat
    return "Outros"

# ----------------- Modelo/tabela -----------------
class Compra(Base):
    __tablename__ = "compras"
    id = Column(Integer, primary_key=True, index=True)
    item = Column(String, index=True)
    marca = Column(String)
    tamanho = Column(String)
    categoria = Column(String, index=True)
    quantidade = Column(Integer)
    valor_unitario = Column(Float)
    valor_total = Column(Float)
    fornecedor = Column(String)
    url = Column(String)
    site = Column(String)
    data_compra = Column(Date, default=date.today)

Base.metadata.create_all(bind=engine)

# ----------------- Schemas -----------------
class ItemRegistro(BaseModel):
    produto: str
    marca: Optional[str] = None
    tamanho: Optional[str] = None
    quantidade: int = 1
    fornecedor: Optional[str] = None
    url: Optional[str] = None
    site: Optional[str] = None
    preco_pago: float
    data: Optional[str] = None

class RegistroCompraRequest(BaseModel):
    itens: List[ItemRegistro]

class RegistroCompraResponse(BaseModel):
    status: str
    inseridos: int

class ResumoItem(BaseModel):
    item: str
    categoria: str
    total_qty: int
    total_gasto: float
    gasto_medio: float

class RelatorioMensalResponse(BaseModel):
    ano: int
    mes: int
    total_gasto: float
    por_item: List[ResumoItem]
    por_categoria: Dict[str, float]

# ----------------- App & CORS -----------------
app = FastAPI(title="Odonto Monitor Preço")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# ----------------- Utilidades -----------------
def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"

def infer_site(url: str) -> str:
    u = (url or "").lower()
    if "dentalcremer" in u:
        return "dentalcremer"
    if "dentalspeed" in u:
        return "dentalspeed"
    if "suryadental" in u:
        return "suryadental"
    return "desconhecido"

def parse_brl_price(text: str) -> Optional[float]:
    if not text:
        return None
    import re
    m = re.search(r"(\d{1,3}(?:\.\d{3})*|\d+),\d{2}", text)
    if not m:
        return None
    raw = m.group(0)
    return float(raw.replace(".", "").replace(",", "."))

def scrape_generic(url: str) -> Dict[str, Any]:
    headers = {
        "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36")
    }
    r = requests.get(url, headers=headers, timeout=20)
    if r.status_code >= 400:
        raise HTTPException(404, detail=f"URL inacessível (status {r.status_code})")

    html = r.text
    soup = BeautifulSoup(html, "html.parser")

    candidates: List[str] = []
    selectors = [
        '[data-testid*="price"]', '[data-test*="price"]',
        '.price', '.value', '.sale-price', '.final-price',
        '.product-price', '.preco', '.valor', '.amount'
    ]
    for sel in selectors:
        for el in soup.select(sel):
            txt = el.get_text(" ", strip=True)
            if txt:
                candidates.append(txt)

    candidates.append(html)

    preco = None
    for c in candidates:
        preco = parse_brl_price(c)
        if preco:
            break

    data = {"url": url, "site": infer_site(url), "timestamp": now_iso()}
    if preco:
        data["preco_atual"] = preco
    return data

# ----------------- Modelos para verificação de preço -----------------
class ItemVigiado(BaseModel):
    url: Optional[str] = None
    preco_pago: float
    produto: Optional[str] = None
    marca: Optional[str] = None
    tamanho: Optional[str] = None
    quantidade: Optional[int] = 1
    fornecedor: Optional[str] = None
    site: Optional[Literal["dentalcremer","dentalspeed","suryadental","desconhecido"]] = None
    data: Optional[str] = None

class VerificarQuedasRequest(BaseModel):
    itens: List[ItemVigiado] = Field(..., min_items=1)

# ----------------- Endpoints -----------------
@app.get("/")
def root():
    return {"status": "ok", "hint": "use /preco?url=... , POST /verificar_quedas , POST /registrar_compra , GET /relatorio_mensal?ano=YYYY&mes=MM"}

@app.get("/health")
def health():
    return {"status": "ok", "time": now_iso()}

@app.get("/preco")
def get_preco(url: str):
    data = scrape_generic(url)
    if "preco_atual" not in data:
        raise HTTPException(404, detail="Preço não encontrado na página.")
    return data

@app.post("/verificar_quedas")
def verificar_quedas(payload: VerificarQuedasRequest):
    baixas = []
    for item in payload.itens:
        if not item.url:
            continue
        atual = scrape_generic(item.url)
        if "preco_atual" not in atual:
            continue
        p_atual = float(atual["preco_atual"])
        if p_atual > 0 and p_atual < float(item.preco_pago):
            baixas.append({
                "item": item.model_dump(),
                "preco_atual": p_atual,
                "diferenca": round(float(item.preco_pago) - p_atual, 2),
                "url": atual["url"],
                "site": atual.get("site", "desconhecido")
            })
    return {"baixas": baixas}

@app.post("/registrar_compra", response_model=RegistroCompraResponse)
def registrar_compra(payload: RegistroCompraRequest):
    db = SessionLocal()
    inseridos = 0
    try:
        for it in payload.itens:
            cat = inferir_categoria(it.produto)
            d = date.today()
            if it.data:
                try:
                    d = datetime.strptime(it.data, "%Y-%m-%d").date()
                except ValueError:
                    pass

            compra = Compra(
                item=it.produto,
                marca=it.marca,
                tamanho=it.tamanho,
                categoria=cat,
                quantidade=int(it.quantidade or 1),
                valor_unitario=float(it.preco_pago),
                valor_total=float(it.preco_pago) * int(it.quantidade or 1),
                fornecedor=it.fornecedor,
                url=it.url,
                site=it.site or infer_site(it.url or ""),
                data_compra=d,
            )
            db.add(compra)
            inseridos += 1

        db.commit()
        return RegistroCompraResponse(status="ok", inseridos=inseridos)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao registrar compras: {e}")
    finally:
        db.close()

@app.get("/relatorio_mensal", response_model=RelatorioMensalResponse)
def relatorio_mensal(
    ano: int = Query(..., ge=2000, le=2100),
    mes: int = Query(..., ge=1, le=12),
):
    db = SessionLocal()
    try:
        inicio = date(ano, mes, 1)
        fim = date(ano + (mes == 12), (mes % 12) + 1, 1)
        compras_q = db.query(Compra).filter(
            Compra.data_compra >= inicio, Compra.data_compra < fim
        )
        total_gasto = float(
            compras_q.with_entities(func.coalesce(func.sum(Compra.valor_total), 0)).scalar() or 0
        )
        rows_item = (
            db.query(
                Compra.item,
                Compra.categoria,
                func.coalesce(func.sum(Compra.quantidade), 0).label("total_qty"),
                func.coalesce(func.sum(Compra.valor_total), 0).label("total_gasto"),
            )
            .filter(Compra.data_compra >= inicio, Compra.data_compra < fim)
            .group_by(Compra.item, Compra.categoria)
            .order_by(func.sum(Compra.valor_total).desc())
            .all()
        )
        por_item: List[ResumoItem] = []
        for r in rows_item:
            qty = int(r.total_qty or 0)
            gasto = float(r.total_gasto or 0)
            por_item.append(
                ResumoItem(
                    item=r.item,
                    categoria=r.categoria or "Outros",
                    total_qty=qty,
                    total_gasto=gasto,
                    gasto_medio=(gasto / qty) if qty else 0.0,
                )
            )
        rows_cat = (
            db.query(
                Compra.categoria,
                func.coalesce(func.sum(Compra.valor_total), 0).label("total_gasto"),
            )
            .filter(Compra.data_compra >= inicio, Compra.data_compra < fim)
            .group_by(Compra.categoria)
            .all()
        )
        por_categoria = { (r.categoria or "Outros"): float(r.total_gasto or 0) for r in rows_cat }
        return RelatorioMensalResponse(
            ano=ano, mes=mes,
            total_gasto=total_gasto,
            por_item=por_item,
            por_categoria=por_categoria,
        )
    finally:
        db.close()

# ---------- Listar compras (opcionalmente filtrar por mês/ano) ----------
@app.get("/compras")
def listar_compras(
    mes: Optional[int] = Query(None, ge=1, le=12),
    ano: Optional[int] = Query(None, ge=2000, le=2100)
):
    db = SessionLocal()
    try:
        query = db.query(Compra)
        if mes and ano:
            inicio = date(ano, mes, 1)
            fim = date(ano + (mes == 12), (mes % 12) + 1, 1)
            query = query.filter(Compra.data_compra >= inicio, Compra.data_compra < fim)
        elif mes:
            ano_atual = date.today().year
            inicio = date(ano_atual, mes, 1)
            fim = date(ano_atual + (mes == 12), (mes % 12) + 1, 1)
            query = query.filter(Compra.data_compra >= inicio, Compra.data_compra < fim)
        elif ano:
            inicio = date(ano, 1, 1)
            fim = date(ano + 1, 1, 1)
            query = query.filter(Compra.data_compra >= inicio, Compra.data_compra < fim)

        compras = query.order_by(Compra.data_compra.desc()).all()
        return {
            "total_registros": len(compras),
            "compras": [
                {
                    "id": c.id,
                    "produto": c.item,
                    "marca": c.marca,
                    "tamanho": c.tamanho,
                    "categoria": c.categoria,
                    "quantidade": c.quantidade,
                    "valor_unitario": c.valor_unitario,
                    "valor_total": c.valor_total,
                    "fornecedor": c.fornecedor,
                    "url": c.url,
                    "site": c.site,
                    "data_compra": c.data_compra.isoformat()
                }
                for c in compras
            ]
        }
    finally:
        db.close()

# (opcional local)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
