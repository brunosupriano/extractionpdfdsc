import customtkinter as ctk
from tkinter import filedialog, messagebox
import pandas as pd
import PyPDF2
import re

# Inicialização CustomTkinter
ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")

# Funções do seu processamento
def to_float_br(v: str):
    if not v:
        return None
    v = v.strip().replace(".", "").replace(",", ".")
    try:
        return float(v)
    except:
        return None

def extrair_texto(pdf_path):
    text = ""
    with open(pdf_path, "rb") as file:
        reader = PyPDF2.PdfReader(file)
        for page in reader.pages:
            text += page.extract_text() or ""
    return text

def parse_pdf_text(texto: str):
    blocos = re.split(r"(?=CASA\s+\d+\s*-\s*BL\.\s*\w+)", texto)

    padrao_item = re.compile(
        r"^\s*\d{1,4}\s*([A-ZÀ-ÿ0-9\.\-\/ ]+?)"
        r"\s*(?:([\d\.,]+)\s*m3)?"
        r"\s+(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})$",
        re.MULTILINE
    )

    dados = []
    for bloco in blocos:
        if "CASA" not in bloco:
            continue
        if "TOTAIS" in bloco:
            bloco = re.split(r"\n\s*TOTAIS\s*:", bloco, maxsplit=1)[0]

        hh = re.search(r"CASA\s+(\d+)\s*-\s*BL\.\s*(\w+)", bloco)
        casa = hh.group(1) if hh else None
        bloco_id = hh.group(2) if hh else None

        registro = {"Casa": casa, "Bloco": bloco_id}

        for nome, consumo, valor in padrao_item.findall(bloco):
            base = nome.strip()
            valor_float = to_float_br(valor)
            if valor_float is not None:
                registro[base] = registro.get(base, 0) + valor_float
            if consumo:
                consumo_float = to_float_br(consumo)
                if consumo_float is not None:
                    registro[f"{base}_Consumo_m3"] = registro.get(f"{base}_Consumo_m3", 0) + consumo_float

        # total sem multa
        m_total = re.search(
            r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})\s*\n\s*"
            r"(?:\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})\s*Com multa",
            bloco, flags=re.MULTILINE
        )
        if m_total:
            registro["TOTAL"] = to_float_br(m_total.group(1))

        dados.append(registro)

    return pd.DataFrame(dados)

# Função do botão
def selecionar_pdf_e_processar():
    pdf_path = filedialog.askopenfilename(
        title="Selecione o arquivo PDF",
        filetypes=[("PDF Files", "*.pdf")]
    )
    if not pdf_path:
        return

    caminho_label.configure(text=pdf_path)

    try:
        texto = extrair_texto(pdf_path)
        df = parse_pdf_text(texto)
        if df.empty:
            messagebox.showwarning("Aviso", "Nenhum dado extraído do PDF!")
            return

        # ordenar colunas
        cols = ["Casa", "Bloco"] + [c for c in df.columns if c not in ("Casa", "Bloco")]
        df = df[cols]

        # Caixa para salvar Excel
        excel_path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
            title="Salvar arquivo Excel"
        )
        if not excel_path:
            return

        df.to_excel(excel_path, index=False)
        messagebox.showinfo("Sucesso", f"Arquivo gerado com sucesso:\n{excel_path}")

    except Exception as e:
        messagebox.showerror("Erro", f"Ocorreu um erro:\n{e}")

# Criar app
app = ctk.CTk()
app.title("Calculador de Valores PDF")
app.geometry("500x200")

botao = ctk.CTkButton(app, text="Selecionar PDF e Calcular", command=selecionar_pdf_e_processar)
botao.pack(pady=30)

caminho_label = ctk.CTkLabel(app, text="Nenhum arquivo selecionado")
caminho_label.pack(pady=10)

app.mainloop()
