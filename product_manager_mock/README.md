# Product Manager mock script

## How to run

`pip3 install -r ./requirements.txt`

Make sure all dependencies installed. 

Edit `product_manager.py` and set correct OpenAI api key (git won't allow pushing with a valid secret there).

Then run the script

`python3 ./product_manager.py`

And follow instructions in command line.



## About this tool

This no more than a test tool for the prompts.

All voice to text / text to voice conversions are done with a simple Google's text to speech engine runnning locally, so don't expet to much from those, these are added mostly for convinience and for more production-like look and feel.
In prod TTS engine must be switched with the one from OpenAI.