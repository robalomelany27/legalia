import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
from openai import OpenAI
from docx import Document
from io import BytesIO
import hashlib
from PyPDF2 import PdfReader
# --- CONFIGURACIÓN E INICIALIZACIÓN ---
st.set_page_config(page_title="LegalAI - Revisor de Contratos", layout="centered")

# INTRODUCE TU API KEY AQUÍ SI NO USAS SECRETS
# client = OpenAI(api_key="sk-TU-CLAVE-AQUI")

# Si usas secrets.toml (Recomendado):
try:
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
except:
    st.warning("⚠️ No se detectó API Key en secrets.toml. La App fallará al intentar analizar.")

# --- BASE DE DATOS (SQLite) ---
def init_db():
    conn = sqlite3.connect('legal_app.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, password TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  username TEXT, 
                  date TEXT, 
                  filename TEXT, 
                  analysis TEXT)''')
    conn.commit()
    conn.close()

def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_hashes(password, hashed_text):
    if make_hashes(password) == hashed_text:
        return True
    return False

def add_user(username, password):
    conn = sqlite3.connect('legal_app.db')
    c = conn.cursor()
    c.execute('INSERT INTO users(username, password) VALUES (?,?)', 
              (username, make_hashes(password)))
    conn.commit()
    conn.close()

def login_user(username, password):
    conn = sqlite3.connect('legal_app.db')
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE username =? AND password = ?', 
              (username, make_hashes(password)))
    data = c.fetchall()
    conn.close()
    return data

def save_analysis(username, filename, analysis):
    conn = sqlite3.connect('legal_app.db')
    c = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('INSERT INTO history(username, date, filename, analysis) VALUES (?,?,?,?)', 
              (username, timestamp, filename, analysis))
    conn.commit()
    conn.close()

def get_user_history(username):
    conn = sqlite3.connect('legal_app.db')
    df = pd.read_sql_query("SELECT date, filename, analysis FROM history WHERE username = ? ORDER BY date DESC", conn, params=(username,))
    conn.close()
    return df

# --- FUNCIONES DE LÓGICA ---

def analyze_contract_text(text_content):
    system_prompt = """
    Eres un abogado experto en derecho inmobiliario argentino. Tu cliente es el inquilino.
    Analiza el contrato proporcionado en busca de cláusulas abusivas, ilegales o riesgosas.
    
    Estructura tu respuesta así:
    1. RESUMEN EJECUTIVO: (2 líneas).
    2. SEMÁFORO DE RIESGO: (Bajo/Medio/Alto).
    3. ANÁLISIS DE CLÁUSULAS: Lista los puntos críticos. Cita siempre el artículo del Código Civil y Comercial (CCyC) o la Ley de Alquileres vigente que justifique tu observación.
    4. RECOMENDACIÓN: ¿Firmar, Negociar o Rechazar?
    
    Usa formato Markdown claro.
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o", # Usa gpt-3.5-turbo si quieres gastar menos
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Analiza este texto legal: {text_content[:15000]}"}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error: {e}"

def create_docx(analysis_text, filename):
    """Genera un archivo Word descargable"""
    doc = Document()
    doc.add_heading(f'Reporte Legal: {filename}', 0)
    
    doc.add_paragraph(f"Fecha de análisis: {datetime.now().strftime('%d/%m/%Y')}")
    doc.add_paragraph("Generado por IA Legal - Revisión preliminar")
    
    doc.add_heading('Análisis Detallado', level=1)
    
    # Insertar el texto del análisis
    # (Para que se vea bien en Word, podríamos limpiar el markdown, 
    # pero insertarlo directo es funcional para MVP)
    doc.add_paragraph(analysis_text)
    
    doc.add_paragraph('---')
    doc.add_paragraph('DISCLAIMER: Este reporte fue generado por inteligencia artificial. No constituye asesoramiento legal vinculante. Consulte a un abogado matriculado.')
    
    # Guardar en memoria (buffer) en lugar de disco
    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

# --- INTERFAZ ---

def main():
    init_db()
    
    # Sidebar Login
    with st.sidebar:
        st.title("⚖️ LegalApp")
        if 'logged_in' not in st.session_state:
            st.session_state['logged_in'] = False
            
        menu = ["Login", "Registro"]
        if st.session_state['logged_in']:
            menu = ["App", "Salir"]
            
        choice = st.selectbox("Navegación", menu)
        
        if choice == "Login":
            username = st.text_input("Usuario")
            password = st.text_input("Contraseña", type='password')
            if st.button("Entrar"):
                if login_user(username, password):
                    st.session_state['logged_in'] = True
                    st.session_state['username'] = username
                    st.rerun()
                else:
                    st.error("Datos incorrectos")
                    
        elif choice == "Registro":
            new_user = st.text_input("Nuevo Usuario")
            new_pass = st.text_input("Nueva Contraseña", type='password')
            if st.button("Crear Cuenta"):
                try:
                    add_user(new_user, new_pass)
                    st.success("Creado. Ve a Login.")
                except:
                    st.warning("Ese usuario ya existe")
                    
        elif choice == "Salir":
            st.session_state['logged_in'] = False
            st.rerun()

    # Main Area
    if st.session_state['logged_in']:
        st.header(f"Bienvenido, {st.session_state['username']}")
        
        tab1, tab2 = st.tabs(["📄 Nuevo Análisis", "🗄️ Historial"])
        
        with tab1:
            st.info("Sube un contrato de alquiler (PDF) para detectar cláusulas ilegales.")
            uploaded_file = st.file_uploader("Contrato", type=['pdf', 'txt'])
            
            if uploaded_file and st.button("Analizar Riesgos"):
                text_content = ""
                
                # Procesamiento de PDF
                if uploaded_file.type == "application/pdf":
                    try:
                        reader = PdfReader(uploaded_file)
                        for page in reader.pages:
                            text_content += page.extract_text()
                    except Exception as e:
                        st.error(f"Error leyendo PDF: {e}")
                else:
                    # Archivos de texto
                    text_content = uploaded_file.getvalue().decode("utf-8")
                
                if text_content:
                    with st.spinner("Consultando jurisprudencia..."):
                        # Llamada a IA
                        analysis = analyze_contract_text(text_content)
                        
                        # Mostrar en pantalla
                        st.markdown("### Resultado del Análisis")
                        st.write(analysis)
                        
                        # Guardar DB
                        save_analysis(st.session_state['username'], uploaded_file.name, analysis)
                        
                        # Generar Word
                        docx_file = create_docx(analysis, uploaded_file.name)
                        
                        st.download_button(
                            label="📥 Descargar Reporte en Word (.docx)",
                            data=docx_file,
                            file_name=f"Reporte_{uploaded_file.name}.docx",
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        )

        with tab2:
            st.subheader("Tus análisis anteriores")
            df = get_user_history(st.session_state['username'])
            if not df.empty:
                st.dataframe(df[['date', 'filename']], use_container_width=True)
                
                # Selector para ver detalles antiguos
                seleccion = st.selectbox("Ver detalle de:", df['filename'].unique())
                if seleccion:
                    reporte = df[df['filename'] == seleccion].iloc[0]['analysis']
                    st.markdown("---")
                    st.markdown(reporte)
                    
                    # Botón para descargar también los viejos
                    docx_viejo = create_docx(reporte, seleccion)
                    st.download_button(
                        label="Descargar este reporte antiguo",
                        data=docx_viejo,
                        file_name=f"Reporte_{seleccion}.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key="old_download"
                    )
            else:
                st.write("Aún no tienes historial.")

    else:
        st.markdown("""
        ### Herramienta de Auditoría Legal con IA
        Esta herramienta utiliza Inteligencia Artificial para revisar contratos y protegerte de cláusulas abusivas.
        
        **Por favor, inicia sesión o regístrate en el menú lateral.**
        """)

if __name__ == '__main__':
    main()
