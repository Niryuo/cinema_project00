from app import create_app

app = create_app()
@app.after_request
def add_charset(response):
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    return response
if __name__ == "__main__":
    app.run(debug=True)