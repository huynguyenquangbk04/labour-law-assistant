Do hiện tại chưa Dockerize:
- Muốn dùng backend thì cài virtual environment trong thư mục backend, sao đó pip install -r requirements.txt, nếu vscode đang mở trực tiếp thư mục backend thì có thể trực tiếp chọn python interpreter của backend venv, còn nếu mở labour-law-assistant thì phải ctrl + shift + p -> select interpreter -> enter interpreter path -> find -> backend/venv/Scripts/python.exe
- Còn khi Dockerize rồi sẽ không còn phức tạp như thế, vì backend sẽ nằm trong một container riêng, các thư viện sẽ được cài thẳng vào môi trường python của container đó thay vì một môi trường venv nào khác. 

Cài PostgreSQL:
- docker compose up -d

Running: 
- Cho phép terminal đọc biến môi trường.
- python -m backend.main.

Ollama: 
- Cài Ollama trên máy.
- ollama pull bge-m3
- ollama pull qwen2.5:3b
