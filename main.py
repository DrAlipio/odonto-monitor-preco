from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Literal
import requests, re, datetime
from bs4 import BeautifulSoup

app = FastAPI()

# --------- Utils ----------
def now_iso():
    return datetime.datetime.utcnow().isoformat() + "Z"

def parse_brl_price(text: str) -> Optional[float]:
    m = re.search(r"(\d{1,3}(?:\.\d{3})*,\d{2})", text)
    if not m: 
        return None
    return float(m.group(1).replace(".", "").replace(",", "."))

def infer_site(url: str) -> str:
    u = url.lower()
    if "cremer" in u: return "dentalcremer"
    if "dentalspeed" in u or "speed" in u: return "dentalspeed"
    if "surya" in u: return "suryadental"
    return "desconhecido"

# tentativa genérica de seletores de preço/nomes (pode ajustar depois)
NAME_SELECTORS = ["h1", "h1.product-name", "h1.product-title"]
PRICE_SELECTORS = [".price", ".product-price", ".final-price", ".sale-price", "[data-testid='price']"]
STOCK_SELECTORS = [".stock", ".availability", "[data-testid='stock']"]

def scrape_generic(url: str):
    r = requests.get(url, timeout=30, headers={"User-Agent":"Mozilla/5.0"})
    if r.status_code != 200:
        raise HTTPException(404, detail=f"Página retornou {r.status_code}")
    soup = BeautifulSoup(r.text, "html.parser")

    def first_text(selectors):
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                t = el.get_text(strip=True)
                if t: return t
        return None

    nome = first_text(NAME_SELECTORS) or "Produto"
    preco_txt = first_text(PRICE_SELECTORS) or ""
    preco = parse_brl_price(preco_txt) or 0.0
    stock_txt = first_text(STOCK_SELECTORS) or ""
    disponivel = not any(x in stock_txt.lower() for x in ["indispon", "sem estoque"])
    return {
        "site": infer_site(url),
        "url": url,
        "nome": nome,
        "variacao": None,
        "disponivel": disponivel,
        "preco_atual": preco,
        "moeda": "BRL",
        "coletado_em": now_iso(),
    }

# --------- Schemas ----------
SiteLiteral = Literal["dentalcremer","dentalspeed","suryadental","desconhecido"]

class ItemVigiado(BaseModel):
    site: Optional[SiteLiteral] = None
    url: Optional[str] = None
    produto: Optional[str] = None
    marca: Optional[str] = None
    tamanho: Optional[str] = None
    preco_pago: float

class VerificarQuedasRequest(BaseModel):
    itens: List[ItemVigiado]

# --------- Endpoints ----------
@app.get("/")
def root():
    return {"status":"ok","hint":"use /preco?url=... ou POST /verificar_quedas"}

@app.get("/health")
def health():
    return {"status":"ok"}

@app.get("/preco")
def get_preco(url: str):
    data = scrape_generic(url)
    if not data["preco_atual"]:
        raise HTTPException(404, detail="Preço não encontrado na página")
    return data

@app.post("/verificar_quedas")
def verificar_quedas(payload: VerificarQuedasRequest):
    baixas = []
    for item in payload.itens:
        if not item.url:
            continue
        atual = scrape_generic(item.url)
        p_atual = float(atual["preco_atual"])
        if p_atual > 0 and p_atual < float(item.preco_pago):
            baixas.append({
                "item": item.model_dump(),
                "preco_atual": p_atual,
                "diferenca": round(float(item.preco_pago) - p_atual, 2),
                "url": atual["url"],
            })
    return {"baixas": baixas}
