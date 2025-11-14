from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import subprocess
import os
import sys
import threading
import time
from datetime import datetime
import logging
import json
import atexit

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Kalıcı depolama dosyaları
PROCESSES_FILE = 'data/processes.json'
BOTS_FILE = 'data/bots.json'

# Klasörleri oluştur
os.makedirs('uploads', exist_ok=True)
os.makedirs('logs', exist_ok=True)
os.makedirs('templates', exist_ok=True)
os.makedirs('data', exist_ok=True)

# Process'leri ve botları yükle
def load_data():
    processes = {}
    bots = []
    
    try:
        if os.path.exists(PROCESSES_FILE):
            with open(PROCESSES_FILE, 'r') as f:
                processes_data = json.load(f)
                # Çalışan process'leri kontrol et
                for bot_name, pid in processes_data.items():
                    try:
                        # Process hala çalışıyor mu kontrol et
                        os.kill(pid, 0)
                        processes[bot_name] = subprocess.Popen(['python', f'uploads/{bot_name}'])
                    except (OSError, subprocess.SubprocessError):
                        # Process ölmüş
                        pass
    except Exception as e:
        logger.error(f"Processes load error: {e}")
    
    try:
        if os.path.exists(BOTS_FILE):
            with open(BOTS_FILE, 'r') as f:
                bots = json.load(f)
    except Exception as e:
        logger.error(f"Bots load error: {e}")
    
    return processes, bots

def save_data():
    try:
        # Processes'i kaydet
        processes_data = {}
        for bot_name, process in processes.items():
            if process.poll() is None:  # Hala çalışıyorsa
                processes_data[bot_name] = process.pid
        
        with open(PROCESSES_FILE, 'w') as f:
            json.dump(processes_data, f)
        
        # Bot listesini kaydet
        with open(BOTS_FILE, 'w') as f:
            json.dump(bots, f)
    except Exception as e:
        logger.error(f"Save data error: {e}")

# Data yükle
processes, bots = load_data()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/health')
def health_check():
    return jsonify({
        "status": "healthy", 
        "uploads_count": len(os.listdir('uploads')) if os.path.exists('uploads') else 0,
        "active_processes": len([p for p in processes.values() if p.poll() is None])
    })

def install_bot_requirements(bot_name):
    requirements_file = f"uploads/{bot_name.replace('.py', '_requirements.txt')}"
    
    if os.path.exists(requirements_file):
        try:
            log_message(f"{bot_name} için requirements yükleniyor: {requirements_file}")
            
            result = subprocess.run([
                sys.executable, "-m", "pip", "install", "-r", requirements_file
            ], capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                log_message(f"{bot_name} requirements başarıyla yüklendi")
                return True
            else:
                log_message(f"Requirements yükleme hatası: {result.stderr}")
                return False
                
        except Exception as e:
            log_message(f"Requirements yükleme hatası: {str(e)}")
            return False
    else:
        log_message(f"{bot_name} için requirements dosyası bulunamadı")
        return True

@app.route('/api/bots')
def list_bots():
    bot_list = []
    
    if os.path.exists('uploads'):
        for file in os.listdir('uploads'):
            if file.endswith('.py'):
                status = "running" if file in processes and processes[file].poll() is None else "stopped"
                requirements_file = f"uploads/{file.replace('.py', '_requirements.txt')}"
                has_requirements = os.path.exists(requirements_file)
                
                bot_list.append({
                    "name": file,
                    "status": status,
                    "has_requirements": has_requirements,
                    "file_path": f"uploads/{file}"
                })
    
    # Bot listesini güncelle ve kaydet
    global bots
    bots = bot_list
    save_data()
    
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
        # Requirements'leri yükle
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
        
        # Output'u oku
        threading.Thread(target=read_output, args=(process, bot_name), daemon=True).start()
        
        # Data kaydet
        save_data()
        
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
        
        # Data kaydet
        save_data()
        
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
        
        # Data kaydet
        save_data()
        
        return jsonify({"status": "success", "message": f"{file.filename} yüklendi"})
    else:
        return jsonify({"error": "Sadece .py ve _requirements.txt dosyaları yüklenebilir"}), 400

@app.route('/api/delete_bot/<bot_name>', methods=['DELETE'])
def delete_bot(bot_name):
    try:
        # Botu durdur
        if bot_name in processes:
            process = processes[bot_name]
            try:
                process.terminate()
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            del processes[bot_name]
        
        # Dosyayı sil
        bot_path = f"uploads/{bot_name}"
        if os.path.exists(bot_path):
            os.remove(bot_path)
        
        # Requirements dosyasını sil
        requirements_path = f"uploads/{bot_name.replace('.py', '_requirements.txt')}"
        if os.path.exists(requirements_path):
            os.remove(requirements_path)
        
        log_message(f"{bot_name} silindi")
        
        # Data kaydet
        save_data()
        
        return jsonify({"status": "success", "message": f"{bot_name} silindi"})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def read_output(process, bot_name):
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
    os.makedirs('logs', exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open('logs/system.log', 'a', encoding='utf-8') as f:
        f.write(f"[{timestamp}] {message}\n")

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

# Uygulama kapanırken data kaydet
atexit.register(save_data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
