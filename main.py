from pydantic import BaseModel
from typing import Optional, List, Literal
import pandas as pd
import os
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any
from datetime import datetime
import requests, re, csv, os
from bs4 import BeautifulSoup

# === DB setup (adicione no topo do arquivo, após seus imports) ===
import os
from datetime import date, datetime
from typing import List, Optional, Dict
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Date, func
)
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()  # carrega .env localmente
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL".lower()) or os.getenv("database_url")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL não definida (Render > Settings > Environment).")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Mapeamento simples para categorizar itens automaticamente (ajuste à vontade)
CATEGORIAS_MAP = {
    "lima": "Endodontia",
    "guta": "Endodontia",
    "algodão": "Básico",
    "escova": "Higiene",
    "anestésico": "Anestesia",
}

def inferir_categoria(nome: str) -> str:
    n = (nome or "").lower()
    for chave, cat in CATEGORIAS_MAP.items():
        if chave in n:
            return cat
    return "Outros"

# --- Modelo da tabela ---
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

# --- Schemas Pydantic ---
class ItemRegistro(BaseModel):
    produto: str = Field(..., description="Nome do item")
    marca: Optional[str] = None
    tamanho: Optional[str] = None
    quantidade: int = 1
    fornecedor: Optional[str] = None
    url: Optional[str] = None
    site: Optional[str] = None
    preco_pago: float = Field(..., description="Valor unitário pago (R$)")
    data: Optional[str] = Field(None, description="YYYY-MM-DD")

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

# Se você já tem `app = FastAPI()`, remova esta linha.
try:
    app
except NameError:
    from fastapi import FastAPI
    app = FastAPI()

from fastapi import HTTPException, Query

# --- Endpoint: registrar compras em lote ---
@app.post("/registrar_compra", response_model=RegistroCompraResponse)
def registrar_compra(payload: RegistroCompraRequest):
    db = SessionLocal()
    inseridos = 0
    try:
        for it in payload.itens:
            cat = inferir_categoria(it.produto)
            # data
            d = None
            if it.data:
                try:
                    d = datetime.strptime(it.data, "%Y-%m-%d").date()
                except ValueError:
                    d = date.today()
            else:
                d = date.today()

            compra = Compra(
                item=it.produto,
                marca=it.marca,
                tamanho=it.tamanho,
                categoria=cat,
                quantidade=it.quantidade,
                valor_unitario=float(it.preco_pago),
                valor_total=float(it.preco_pago) * int(it.quantidade),
                fornecedor=it.fornecedor,
                url=it.url,
                site=it.site,
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

# --- Endpoint: relatório mensal (resumo por item e por categoria) ---
@app.get("/relatorio_mensal", response_model=RelatorioMensalResponse)
def relatorio_mensal(
    ano: int = Query(..., ge=2000, le=2100),
    mes: int = Query(..., ge=1, le=12),
):
    db = SessionLocal()
    try:
        # intervalo do mês
        inicio = date(ano, mes, 1)
        # pegar o primeiro dia do próximo mês
        if mes == 12:
            fim = date(ano + 1, 1, 1)
        else:
            fim = date(ano, mes + 1, 1)

        # todas compras do mês
        compras = db.query(Compra).filter(
            Compra.data_compra >= inicio, Compra.data_compra < fim
        )

        total_gasto = float(compras.with_entities(func.coalesce(func.sum(Compra.valor_total), 0)).scalar() or 0)

        # grupo por item
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
            gast = float(r.total_gasto or 0)
            por_item.append(
                ResumoItem(
                    item=r.item,
                    categoria=r.categoria or "Outros",
                    total_qty=qty,
                    total_gasto=gast,
                    gasto_medio=(gast / qty) if qty else 0.0,
                )
            )

        # grupo por categoria
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
            ano=ano,
            mes=mes,
            total_gasto=total_gasto,
            por_item=por_item,
            por_categoria=por_categoria,
        )
    finally:
        db.close()


app = FastAPI(title="Odonto Monitor Preço")

# CORS liberado (o GPT chama a API do seu domínio Render)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Utilidades ----------

def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"

def infer_site(url: str) -> str:
    u = url.lower()
    if "dentalcremer" in u:
        return "dentalcremer"
    if "dentalspeed" in u:
        return "dentalspeed"
    if "suryadental" in u:
        return "suryadental"
    return "desconhecido"

# R$ 1.234,56 -> 1234.56
def parse_brl_price(text: str) -> Optional[float]:
    if not text:
        return None
    # captura 1.234,56 / 12,34 / 1234,56
    m = re.search(r"(\d{1,3}(?:\.\d{3})*|\d+),\d{2}", text)
    if not m:
        return None
    raw = m.group(0)
    return float(raw.replace(".", "").replace(",", "."))

def scrape_generic(url: str) -> Dict[str, Any]:
    """Tenta achar o preço na página usando seletores comuns e fallback por regex."""
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    }
    r = requests.get(url, headers=headers, timeout=20)
    if r.status_code >= 400:
        raise HTTPException(404, detail=f"URL inacessível (status {r.status_code})")

    html = r.text
    soup = BeautifulSoup(html, "html.parser")

    # seletores mais comuns em e-commerce (ajuda, mas não garante)
    candidates = []
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

    # também procura por R$ via regex no HTML bruto (fallback)
    candidates.append(html)

    preco = None
    for c in candidates:
        preco = parse_brl_price(c)
        if preco:
            break

    data = {
        "url": url,
        "site": infer_site(url),
        "timestamp": now_iso(),
    }
    if preco:
        data["preco_atual"] = preco
    return data

# ---------- Modelos de entrada ----------

class ItemVigiado(BaseModel):
    url: Optional[str] = None
    preco_pago: float
    produto: Optional[str] = None
    marca: Optional[str] = None
    tamanho: Optional[str] = None
    quantidade: Optional[int] = 1
    fornecedor: Optional[str] = None
    site: Optional[Literal["dentalcremer","dentalspeed","suryadental","desconhecido"]] = None
    data: Optional[str] = None  # YYYY-MM-DD

class VerificarQuedasRequest(BaseModel):
    itens: List[ItemVigiado] = Field(..., min_items=1)

class RegistrarCompraBody(BaseModel):
    itens: List[ItemVigiado] = Field(..., min_items=1)

# ---------- Endpoints básicos ----------

@app.get("/")
def root():
    return {"status": "ok", "hint": "use /preco?url=... , POST /verificar_quedas , POST /registrar_compra"}

@app.get("/health")
def health():
    return {"status": "ok", "time": now_iso()}

# ---------- /preco ----------

@app.get("/preco")
def get_preco(url: str):
    data = scrape_generic(url)
    if "preco_atual" not in data:
        raise HTTPException(404, detail="Preço não encontrado na página.")
    return data

# ---------- /verificar_quedas ----------

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

# ---------- /registrar_compra ----------

CSV_FILE = "compras.csv"
CSV_HEADERS = [
    "data","produto","marca","tamanho","quantidade",
    "fornecedor","url","site","preco_pago"
]

def ensure_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            w.writeheader()

@app.post("/registrar_compra")
def registrar_compra(body: RegistrarCompraBody):
    ensure_csv()
    salvos = 0
    erros: List[str] = []

    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        for it in body.itens:
            try:
                row = {
                    "data": it.data or datetime.utcnow().strftime("%Y-%m-%d"),
                    "produto": it.produto or "",
                    "marca": it.marca or "",
                    "tamanho": it.tamanho or "",
                    "quantidade": it.quantidade or 1,
                    "fornecedor": it.fornecedor or "",
                    "url": it.url or "",
                    "site": it.site or infer_site(it.url or ""),
                    "preco_pago": float(it.preco_pago),
                }
                w.writerow(row)
                salvos += 1
            except Exception as e:
                erros.append(str(e))

    return {"salvos": salvos, "erros": erros, "arquivo": CSV_FILE}

# (opcional para rodar local)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
# =========================
# REGISTRO DE COMPRAS (CSV)
# =========================

CSV_PATH = os.environ.get("CSV_PATH", "/tmp/compras.csv")

class ItemCompra(BaseModel):
    produto: str
    marca: Optional[str] = None
    tamanho: Optional[str] = None
    quantidade: Optional[int] = 1
    fornecedor: Optional[str] = None
    url: Optional[str] = None
    site: Optional[Literal["dentalcremer", "dentalspeed", "suryadental", "desconhecido"]] = "desconhecido"
    preco_pago: float
    data: Optional[str] = None  # formato "YYYY-MM-DD"

class RegistrarCompraRequest(BaseModel):
    itens: List[ItemCompra]

def now_iso() -> str:
    # (se você já tiver now_iso() definido acima, pode remover esta função duplicada)
    try:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return datetime.utcnow().isoformat() + "Z"

def _salvar_itens_em_csv(itens: List[ItemCompra]) -> dict:
    linhas = []
    for it in itens:
        linhas.append({
            "timestamp": now_iso(),
            "data": it.data or now_iso()[:10],
            "produto": it.produto,
            "marca": it.marca or "",
            "tamanho": it.tamanho or "",
            "quantidade": int(it.quantidade or 1),
            "fornecedor": it.fornecedor or "",
            "site": it.site,
            "url": it.url or "",
            "preco_pago": float(it.preco_pago),
        })

    df_novo = pd.DataFrame(linhas)

    # Garante diretório e faz append
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    if os.path.exists(CSV_PATH):
        df_antigo = pd.read_csv(CSV_PATH)
        df_all = pd.concat([df_antigo, df_novo], ignore_index=True)
    else:
        df_all = df_novo

    df_all.to_csv(CSV_PATH, index=False)
    return {"ok": True, "salvos": len(linhas), "arquivo": CSV_PATH}

@app.post("/registrar_compra")
def registrar_compra(payload: RegistrarCompraRequest):
    """
    Registra itens de compra em um CSV no servidor.
    Corpo esperado:
    {
      "itens": [
        {
          "produto": "Nome",
          "marca": "Opcional",
          "tamanho": "Opcional",
          "quantidade": 1,
          "fornecedor": "Opcional",
          "url": "Opcional",
          "site": "dentalspeed|dentalcremer|suryadental|desconhecido",
          "preco_pago": 99.9,
          "data": "YYYY-MM-DD"   # opcional
        }
      ]
    }
    """
    res = _salvar_itens_em_csv(payload.itens)
    return res
