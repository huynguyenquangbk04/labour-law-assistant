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

Gemini: 
- Sẽ thử nghiệm API của Google AI Studio xem có làm prototype thay thế Ollama được không.

Thư viện: 
- Do quá trình install và uninstall có nhiều thư viện dư thừa nên cần phải reset lại file venv, requirements.txt.

Docker: 
- Làm thế nào để bỏ các model Ollma và docker.
- Postgres tự động lưu lại volumes nên phải docker compose down -v
- Xóa các file __pycache__ khi muốn đổi model
- Các tiến trình cha, con không được dẹp sạch sẽ khi dùng reload = True + python -m backend.main

Graph: 
- Xem graph đã tối ưu hóa chưa