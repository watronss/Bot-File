from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import subprocess
import os
import threading
import time
from datetime import datetime
import logging

app = Flask(__name__)
CORS(app)

# Log ayarları
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Process'leri saklayacağımız yer
processes = {}

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/bots')
def list_bots():
    bot_list = []
    
    # Uploads klasöründeki tüm .py dosyalarını bul
    if os.path.exists('uploads'):
        for file in os.listdir('uploads'):
            if file.endswith('.py'):
                status = "running" if file in processes and processes[file].poll() is None else "stopped"
                
                bot_list.append({
                    "name": file,
                    "status": status,
                    "file_path": f"uploads/{file}"
                })
    
    return jsonify(bot_list)

@app.route('/api/run_bot', methods=['POST'])
def run_bot():
    data = request.json
    bot_name = data.get('bot_name')
    bot_path = f"uploads/{bot_name}"
    
    if not os.path.exists(bot_path):
        return jsonify({"error": "Bot dosyası bulunamadı"}), 404
    
    # Eğer zaten çalışıyorsa durdur
    if bot_name in processes and processes[bot_name].poll() is None:
        return jsonify({"error": "Bot zaten çalışıyor"}), 400
    
    try:
        # Botu subprocess olarak çalıştır
        process = subprocess.Popen(
            ['python', bot_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        processes[bot_name] = process
        log_message(f"{bot_name} çalıştırıldı (PID: {process.pid})")
        
        # Output'u oku ve logla
        threading.Thread(target=read_output, args=(process, bot_name), daemon=True).start()
        
        return jsonify({"status": "success", "message": f"{bot_name} çalıştırıldı"})
    
    except Exception as e:
        log_message(f"{bot_name} çalıştırılırken hata: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/stop_bot', methods=['POST'])
def stop_bot():
    data = request.json
    bot_name = data.get('bot_name')
    
    if bot_name in processes:
        process = processes[bot_name]
        try:
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        
        del processes[bot_name]
        log_message(f"{bot_name} durduruldu")
        return jsonify({"status": "success", "message": f"{bot_name} durduruldu"})
    else:
        return jsonify({"error": "Bot çalışmıyor"}), 400

@app.route('/api/logs/<bot_name>')
def get_bot_logs(bot_name):
    log_file = f"logs/{bot_name}.log"
    if os.path.exists(log_file):
        with open(log_file, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        return "Henüz log yok"

@app.route('/api/logs/system')
def get_system_logs():
    log_file = "logs/system.log"
    if os.path.exists(log_file):
        with open(log_file, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        return "Henüz sistem logu yok"

@app.route('/api/upload', methods=['POST'])
def upload_bot():
    if 'file' not in request.files:
        return jsonify({"error": "Dosya yok"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Dosya seçilmedi"}), 400
    
    if file and file.filename.endswith('.py'):
        # Uploads klasörüne kaydet
        os.makedirs('uploads', exist_ok=True)
        file.save(f"uploads/{file.filename}")
        
        log_message(f"{file.filename} yüklendi")
        return jsonify({"status": "success", "message": f"{file.filename} yüklendi"})
    else:
        return jsonify({"error": "Sadece .py dosyaları yüklenebilir"}), 400

def read_output(process, bot_name):
    """Process output'unu oku ve logla"""
    os.makedirs('logs', exist_ok=True)
    log_file = f"logs/{bot_name}.log"
    
    with open(log_file, 'a', encoding='utf-8') as f:
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                log_line = f"[{timestamp}] {output}"
                f.write(log_line)
                f.flush()

def log_message(message):
    """Sistem mesajlarını logla"""
    os.makedirs('logs', exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open('logs/system.log', 'a', encoding='utf-8') as f:
        f.write(f"[{timestamp}] {message}\n")

if __name__ == '__main__':
    # Gerekli klasörleri oluştur
    os.makedirs('uploads', exist_ok=True)
    os.makedirs('logs', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    
    app.run(host='0.0.0.0', port=5000, debug=True)
