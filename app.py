from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import subprocess
import os
import sys
import threading
import time
from datetime import datetime
import logging

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

processes = {}

@app.route('/')
def home():
    return render_template('index.html')

def install_bot_requirements(bot_name):
    """Botun özel requirements'ini yükle"""
    requirements_file = f"uploads/{bot_name.replace('.py', '_requirements.txt')}"
    
    if os.path.exists(requirements_file):
        try:
            log_message(f"{bot_name} için requirements yükleniyor: {requirements_file}")
            
            # Pip install işlemi
            result = subprocess.run([
                sys.executable, "-m", "pip", "install", "-r", requirements_file
            ], capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                log_message(f"{bot_name} requirements başarıyla yüklendi")
                return True
            else:
                log_message(f"Requirements yükleme hatası: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            log_message(f"Requirements yükleme timeout: {bot_name}")
            return False
        except Exception as e:
            log_message(f"Requirements yükleme hatası: {str(e)}")
            return False
    else:
        log_message(f"{bot_name} için requirements dosyası bulunamadı: {requirements_file}")
        return True  # Requirements dosyası yoksa devam et

@app.route('/api/bots')
def list_bots():
    bot_list = []
    
    if os.path.exists('uploads'):
        for file in os.listdir('uploads'):
            if file.endswith('.py'):
                status = "running" if file in processes and processes[file].poll() is None else "stopped"
                
                # Requirements dosyası var mı kontrol et
                requirements_file = f"uploads/{file.replace('.py', '_requirements.txt')}"
                has_requirements = os.path.exists(requirements_file)
                
                bot_list.append({
                    "name": file,
                    "status": status,
                    "has_requirements": has_requirements,
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
    
    if bot_name in processes and processes[bot_name].poll() is None:
        return jsonify({"error": "Bot zaten çalışıyor"}), 400
    
    try:
        # Önce requirements'leri yükle
        requirements_ok = install_bot_requirements(bot_name)
        
        if not requirements_ok:
            return jsonify({"error": "Requirements yükleme başarısız"}), 500
        
        # Botu çalıştır
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
        
        threading.Thread(target=read_output, args=(process, bot_name), daemon=True).start()
        
        return jsonify({
            "status": "success", 
            "message": f"{bot_name} çalıştırıldı",
            "has_requirements": requirements_ok
        })
    
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

@app.route('/api/upload', methods=['POST'])
def upload_bot():
    if 'file' not in request.files:
        return jsonify({"error": "Dosya yok"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Dosya seçilmedi"}), 400
    
    if file and (file.filename.endswith('.py') or file.filename.endswith('_requirements.txt')):
        os.makedirs('uploads', exist_ok=True)
        file.save(f"uploads/{file.filename}")
        
        log_message(f"{file.filename} yüklendi")
        return jsonify({"status": "success", "message": f"{file.filename} yüklendi"})
    else:
        return jsonify({"error": "Sadece .py ve _requirements.txt dosyaları yüklenebilir"}), 400

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
    os.makedirs('uploads', exist_ok=True)
    os.makedirs('logs', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    
    app.run(host='0.0.0.0', port=5000, debug=True)
