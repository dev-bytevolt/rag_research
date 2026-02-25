# Python test scripts to benchmark different methods of data delivery to OpenAI

Each `*.py` file is a standalone script. `Jira.csv` is a dummy data set

`csv_file_code_interpreter.py` - benchmarks a csv file loaded into OpenAI and passed through the code interpreter tool to the model

`MCP_server.py` - runs an MCP server that is available to the model. The server can perform a set of queries to an external DB. Make sure to set a correct host name for your enviroinment, use ngrok for example.

`functions_tools.py` - similar to MCP variant, but instead of MCP server makes a function available to OpenAI and the function can perform the same query.

`stream_response.py` - test script that streams the long model response and reads it out loud with TTS, doesn't have to wait for the request completion and starts reading the response as soon as anythiong is available.

`stream_response_CSV.py` - `csv_file_code_interpreter.py` and `stream_response.py` combined - in two queries to OpenAI hides the loading progress behind intermitent phrases.

`stream_response_MCP_server.py` - same thing, `MCP_server.py` and `stream_response.py` combined - in two queries to OpenAI hides the loading progress behind intermitent phrases.

