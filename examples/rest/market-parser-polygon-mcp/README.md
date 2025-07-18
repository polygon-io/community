# Market Parser Demo

A Python CLI for natural language financial queries using the Polygon.io MCP server and Anthropic Claude (via PydanticAI).

## Features

- **Ask questions like:**  
  `Tesla price now`  
  `AAPL volume last week`  
  `Show me the price of MSFT on 2023-01-01`

- **No boilerplate:**  
  All logic is in `market_parser_demo.py`—no package structure, no extra files.

- **Rich CLI output:**  
  Answers are formatted for easy reading in your terminal.

---

## Quickstart (with [uv](https://github.com/astral-sh/uv))

1. **Install [uv](https://github.com/astral-sh/uv) if you don’t have it:**
    ```sh
    curl -Ls https://astral.sh/uv/install.sh | sh
    ```

2. **Get your API keys:**
   - [Polygon.io API key](https://polygon.io/)
   - [Anthropic API key (Claude)](https://console.anthropic.com/)

3. **Create a `.env` file in the same directory as `market_parser_demo.py`:**
    ```
    POLYGON_API_KEY=your_polygon_api_key_here
    ANTHROPIC_API_KEY=your_anthropic_api_key_here
    ```
    Both keys are required for the CLI to work.

4. **Run the CLI (dependencies will be auto-installed from `pyproject.toml`):**
    ```sh
    uv run market_parser_demo.py
    ```

5. **Type your question and press Enter!**  
   Type `exit` to quit.

---

## Example Usage

```
> Tesla price now
✔ Query processed successfully!
Agent Response:
$TSLA is currently trading at $XXX.XX (as of 2024-06-07 15:30:00 UTC).
---------------------

> exit
Goodbye!
```

---

## Troubleshooting

- **Missing API Key:**  
  If you see an error about `POLYGON_API_KEY` or `ANTHROPIC_API_KEY`, make sure your `.env` file is in the same directory and contains both keys:
  ```
  POLYGON_API_KEY=your_polygon_api_key_here
  ANTHROPIC_API_KEY=your_anthropic_api_key_here
  ```

- **Dependencies:**  
  If you get `ModuleNotFoundError`, make sure your `pyproject.toml` lists:
    - `python-dotenv`
    - `rich`
    - `pydantic_ai`

  If you prefer, you can use pip instead:
  ```sh
  pip install python-dotenv rich pydantic_ai
  python market_parser_demo.py
  ```

- **Other errors:**  
  All errors are printed in red in the terminal for easy debugging.

---

## How it Works

- Loads your Polygon and Anthropic API keys from `.env`
- Starts the Polygon MCP server in the background
- Sends your natural language query to Anthropic Claude via PydanticAI
- Prints the answer in a readable format

---

## License

MIT (or your preferred license) 