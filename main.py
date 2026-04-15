"""
TRANSCOZZA VIAGENS - Backend FastAPI
"""
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from typing import Optional, List
import os
import uuid
import random
import string
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from supabase import create_client, Client
from dotenv import load_dotenv
import httpx

load_dotenv()

# ─── Supabase ───────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")
SUPABASE_BUCKET = "viagens-docs"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)

# ─── App ────────────────────────────────────────────────
app = FastAPI(title="Transcozza Viagens API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Models ─────────────────────────────────────────────
class CriarViagemRequest(BaseModel):
    container: str
    di: str
    motorista: str
    placa: Optional[str] = ""
    email_cliente: Optional[str] = ""
    email_despachante: Optional[str] = ""
    email_operador: Optional[str] = ""

# ─── Helpers ────────────────────────────────────────────
def gerar_trip_code(length=6):
    chars = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(random.choices(chars, k=length))
        result = supabase.table("viagens").select("id").eq("trip_code", code).execute()
        if not result.data:
            return code

def enviar_email(destinatarios: List[str], assunto: str, corpo_html: str, anexos: List[dict] = []):
    """Envia e-mail via Zoho SMTP com anexos opcionais"""
    ZOHO_EMAIL = os.getenv("ZOHO_EMAIL")
    ZOHO_PASSWORD = os.getenv("ZOHO_PASSWORD")

    msg = MIMEMultipart("mixed")
    msg["From"] = f"Transcozza Express <{ZOHO_EMAIL}>"
    msg["To"] = ", ".join(destinatarios)
    msg["Subject"] = assunto

    msg.attach(MIMEText(corpo_html, "html"))

    for anexo in anexos:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(anexo["bytes"])
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{anexo["filename"]}"')
        msg.attach(part)

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL("smtp.zoho.com", 465, context=context) as server:
            server.login(ZOHO_EMAIL, ZOHO_PASSWORD)
            server.sendmail(ZOHO_EMAIL, destinatarios, msg.as_string())
        return True
    except Exception as e:
        print(f"Erro ao enviar e-mail: {e}")
        return False

def template_email_etapa1(viagem: dict, foto_urls: List[str]) -> str:
    fotos_html = "".join([
        f'<a href="{url}" style="display:inline-block;margin:6px">'
        f'<img src="{url}" style="width:200px;height:150px;object-fit:cover;border-radius:8px;border:1px solid #ddd"/>'
        f'</a>' for url in foto_urls
    ])
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#f8f9fa;padding:20px;border-radius:12px">
      <div style="background:#0a0e1a;padding:20px;border-radius:8px;text-align:center;margin-bottom:20px">
        <h1 style="color:#00d4ff;margin:0;font-size:22px">📦 Transcozza Express</h1>
        <p style="color:#6b7fa3;margin:5px 0 0">Sistema de Rastreamento de Documentos</p>
      </div>
      <div style="background:white;padding:24px;border-radius:8px;margin-bottom:16px">
        <h2 style="color:#0a0e1a;margin-top:0">Retirada do Container Confirmada</h2>
        <table style="width:100%;border-collapse:collapse">
          <tr><td style="padding:8px;color:#666;width:140px">Container</td><td style="padding:8px;font-weight:bold">{viagem['container']}</td></tr>
          <tr style="background:#f8f9fa"><td style="padding:8px;color:#666">DI / Referência</td><td style="padding:8px;font-weight:bold">{viagem['di']}</td></tr>
          <tr><td style="padding:8px;color:#666">Motorista</td><td style="padding:8px">{viagem['motorista']}</td></tr>
          <tr style="background:#f8f9fa"><td style="padding:8px;color:#666">Placa</td><td style="padding:8px">{viagem.get('placa','—')}</td></tr>
          <tr><td style="padding:8px;color:#666">Data/Hora</td><td style="padding:8px">{datetime.now().strftime('%d/%m/%Y às %H:%M')}</td></tr>
        </table>
      </div>
      <div style="background:white;padding:24px;border-radius:8px">
        <h3 style="color:#0a0e1a;margin-top:0">📸 Fotos da Retirada</h3>
        <div style="text-align:center">{fotos_html}</div>
      </div>
      <p style="text-align:center;color:#999;font-size:12px;margin-top:16px">
        Transcozza Express · Sistema automático de documentação de viagens
      </p>
    </div>"""

def template_email_etapa2(viagem: dict, foto_urls: List[str]) -> str:
    fotos_html = "".join([
        f'<a href="{url}"><img src="{url}" style="width:200px;height:150px;object-fit:cover;border-radius:8px;border:1px solid #ddd;margin:6px"/></a>'
        for url in foto_urls
    ])
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#f8f9fa;padding:20px;border-radius:12px">
      <div style="background:#0a0e1a;padding:20px;border-radius:8px;text-align:center;margin-bottom:20px">
        <h1 style="color:#ff6b35;margin:0;font-size:22px">🗂️ Transcozza Express</h1>
        <p style="color:#6b7fa3;margin:5px 0 0">CTE Carimbado Recebido</p>
      </div>
      <div style="background:white;padding:24px;border-radius:8px;margin-bottom:16px">
        <h2 style="color:#0a0e1a;margin-top:0">Entrega no Cliente Confirmada</h2>
        <table style="width:100%;border-collapse:collapse">
          <tr><td style="padding:8px;color:#666;width:140px">Container</td><td style="padding:8px;font-weight:bold">{viagem['container']}</td></tr>
          <tr style="background:#f8f9fa"><td style="padding:8px;color:#666">DI / Referência</td><td style="padding:8px;font-weight:bold">{viagem['di']}</td></tr>
          <tr><td style="padding:8px;color:#666">Motorista</td><td style="padding:8px">{viagem['motorista']}</td></tr>
          <tr style="background:#f8f9fa"><td style="padding:8px;color:#666">Data/Hora</td><td style="padding:8px">{datetime.now().strftime('%d/%m/%Y às %H:%M')}</td></tr>
        </table>
      </div>
      <div style="background:white;padding:24px;border-radius:8px">
        <h3 style="color:#0a0e1a;margin-top:0">📸 CTE Carimbado</h3>
        <div style="text-align:center">{fotos_html}</div>
      </div>
      <p style="text-align:center;color:#999;font-size:12px;margin-top:16px">Transcozza Express · Sistema automático</p>
    </div>"""

def template_email_etapa3(viagem: dict, foto_urls: List[str]) -> str:
    fotos_html = "".join([
        f'<a href="{url}"><img src="{url}" style="width:200px;height:150px;object-fit:cover;border-radius:8px;border:1px solid #ddd;margin:6px"/></a>'
        for url in foto_urls
    ])
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#f8f9fa;padding:20px;border-radius:12px">
      <div style="background:#0a0e1a;padding:20px;border-radius:8px;text-align:center;margin-bottom:20px">
        <h1 style="color:#00ff88;margin:0;font-size:22px">✅ Transcozza Express</h1>
        <p style="color:#6b7fa3;margin:5px 0 0">Container Devolvido</p>
      </div>
      <div style="background:white;padding:24px;border-radius:8px;margin-bottom:16px">
        <h2 style="color:#0a0e1a;margin-top:0">Devolução do Container Confirmada</h2>
        <table style="width:100%;border-collapse:collapse">
          <tr><td style="padding:8px;color:#666;width:140px">Container</td><td style="padding:8px;font-weight:bold">{viagem['container']}</td></tr>
          <tr style="background:#f8f9fa"><td style="padding:8px;color:#666">DI / Referência</td><td style="padding:8px;font-weight:bold">{viagem['di']}</td></tr>
          <tr><td style="padding:8px;color:#666">Motorista</td><td style="padding:8px">{viagem['motorista']}</td></tr>
          <tr style="background:#f8f9fa"><td style="padding:8px;color:#666">Data/Hora</td><td style="padding:8px">{datetime.now().strftime('%d/%m/%Y às %H:%M')}</td></tr>
        </table>
      </div>
      <div style="background:white;padding:24px;border-radius:8px">
        <h3 style="color:#0a0e1a;margin-top:0">📸 Comprovante de Devolução</h3>
        <div style="text-align:center">{fotos_html}</div>
      </div>
      <p style="text-align:center;color:#999;font-size:12px;margin-top:16px">Transcozza Express · Sistema automático</p>
    </div>"""

# ─── Routes ─────────────────────────────────────────────

@app.get("/")
def health():
    return {"status": "ok", "service": "Transcozza Viagens API"}

# Criar viagem
@app.post("/viagens")
async def criar_viagem(body: CriarViagemRequest):
    trip_code = gerar_trip_code()
    data = {
        "trip_code": trip_code,
        "container": body.container.upper().strip(),
        "di": body.di.strip(),
        "motorista": body.motorista.strip(),
        "placa": body.placa.strip() if body.placa else "",
        "email_cliente": body.email_cliente.strip() if body.email_cliente else "",
        "email_despachante": body.email_despachante.strip() if body.email_despachante else "",
        "email_operador": body.email_operador.strip() if body.email_operador else "",
        "status": "ativa",
        "step1_status": "pendente",
        "step2_status": "pendente",
        "step3_status": "pendente",
    }
    result = supabase.table("viagens").insert(data).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Erro ao criar viagem")
    return {"success": True, "trip_code": trip_code, "viagem": result.data[0]}

# Buscar viagem por código
@app.get("/viagens/{trip_code}")
async def buscar_viagem(trip_code: str):
    result = supabase.table("viagens").select("*").eq("trip_code", trip_code.upper()).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Viagem não encontrada")
    viagem = result.data[0]
    docs = supabase.table("documentos").select("*").eq("trip_code", trip_code.upper()).execute()
    viagem["documentos"] = docs.data or []
    return viagem

# Listar todas as viagens
@app.get("/viagens")
async def listar_viagens(status: Optional[str] = None):
    query = supabase.table("viagens").select("*").order("created_at", desc=True)
    if status:
        query = query.eq("status", status)
    result = query.execute()
    return {"viagens": result.data or []}

# Upload de fotos por etapa
@app.post("/viagens/{trip_code}/etapa/{etapa}")
async def upload_etapa(
    trip_code: str,
    etapa: int,
    fotos: List[UploadFile] = File(...)
):
    if etapa not in [1, 2, 3]:
        raise HTTPException(status_code=400, detail="Etapa inválida")

    # Buscar viagem
    result = supabase.table("viagens").select("*").eq("trip_code", trip_code.upper()).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Viagem não encontrada")
    viagem = result.data[0]

    foto_urls = []
    fotos_bytes_list = []

    # Salvar cada foto no Storage
    for foto in fotos:
        conteudo = await foto.read()
        ext = foto.filename.split(".")[-1] if "." in foto.filename else "jpg"
        filename = f"{trip_code}/etapa{etapa}/{uuid.uuid4()}.{ext}"

        # Upload para Supabase Storage
        storage_result = supabase.storage.from_(SUPABASE_BUCKET).upload(
            filename,
            conteudo,
            {"content-type": foto.content_type or "image/jpeg"}
        )

        # Gerar URL pública
        url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(filename)
        foto_urls.append(url)
        fotos_bytes_list.append({"bytes": conteudo, "filename": foto.filename})

        # Salvar no banco
        supabase.table("documentos").insert({
            "viagem_id": viagem["id"],
            "trip_code": trip_code.upper(),
            "etapa": etapa,
            "tipo": _tipo_por_etapa(etapa, foto.filename),
            "storage_path": filename,
            "storage_url": url,
            "filename": foto.filename,
        }).execute()

    # Atualizar status da etapa
    campo_status = f"step{etapa}_status"
    campo_at = f"step{etapa}_at"
    supabase.table("viagens").update({
        campo_status: "enviado",
        campo_at: datetime.utcnow().isoformat(),
    }).eq("trip_code", trip_code.upper()).execute()

    # Verificar se todas etapas concluídas
    viagem_atualizada = supabase.table("viagens").select("*").eq("trip_code", trip_code.upper()).execute().data[0]
    if all(viagem_atualizada[f"step{i}_status"] == "enviado" for i in [1,2,3]):
        supabase.table("viagens").update({"status": "concluida"}).eq("trip_code", trip_code.upper()).execute()

    # Enviar e-mails conforme etapa
    _enviar_emails_etapa(etapa, viagem, foto_urls, fotos_bytes_list)

    return {"success": True, "etapa": etapa, "fotos": len(foto_urls), "urls": foto_urls}

def _tipo_por_etapa(etapa: int, filename: str) -> str:
    tipos = {1: "retirada", 2: "cte", 3: "devolucao"}
    return tipos.get(etapa, "documento")

def _enviar_emails_etapa(etapa: int, viagem: dict, foto_urls: List[str], fotos_bytes: List[dict]):
    destinatarios = []
    assunto = ""
    corpo = ""

    if etapa == 1:
        if viagem.get("email_cliente"):
            destinatarios.append(viagem["email_cliente"])
        assunto = f"📦 [{viagem['container']}] Retirada do Container Confirmada"
        corpo = template_email_etapa1(viagem, foto_urls)

    elif etapa == 2:
        if viagem.get("email_operador"):
            destinatarios.append(viagem["email_operador"])
        assunto = f"🗂️ [{viagem['container']}] CTE Carimbado Recebido"
        corpo = template_email_etapa2(viagem, foto_urls)

    elif etapa == 3:
        if viagem.get("email_cliente"):
            destinatarios.append(viagem["email_cliente"])
        if viagem.get("email_despachante"):
            destinatarios.append(viagem["email_despachante"])
        assunto = f"✅ [{viagem['container']}] Container Devolvido"
        corpo = template_email_etapa3(viagem, foto_urls)

    if destinatarios:
        sucesso = enviar_email(destinatarios, assunto, corpo, fotos_bytes)
        # Log no banco
        for dest in destinatarios:
            supabase.table("email_logs").insert({
                "viagem_id": viagem["id"],
                "trip_code": viagem["trip_code"],
                "etapa": etapa,
                "destinatario": dest,
                "status": "enviado" if sucesso else "erro",
            }).execute()

# Deletar viagem
@app.delete("/viagens/{trip_code}")
async def deletar_viagem(trip_code: str):
    result = supabase.table("viagens").select("id").eq("trip_code", trip_code.upper()).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Viagem não encontrada")
    supabase.table("viagens").update({"status": "cancelada"}).eq("trip_code", trip_code.upper()).execute()
    return {"success": True}
