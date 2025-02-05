import os, re, sys, csv, glob, time
import openai
import tiktoken
import pdfplumber
from openai.error import RateLimitError, APIError
from openai.embeddings_utils import get_embedding
from pathlib import Path
import pandas as pd
import numpy as np
from PyPDF2 import PdfWriter, PdfReader

MAX_TOKENS = 16384
TOKEN_BUFFER = 1000

def set_api_key():
    try:
        openai.api_key = os.getenv('OPENAI_API_KEY')
    except KeyError:
        print("Set your OpenAI API key as an environment variable named 'OPENAI_API_KEY' eg In terminal: export OPENAI_API_KEY=your-api-key")

def handle_api_error(func):
    def wrapper(*args, **kwargs):
        while True:
            try:
                return func(*args, **kwargs)
            except (RateLimitError, APIError):
                print('API Error. Waiting 10s before retrying.')
                time.sleep(10)  # wait for 10 seconds before retrying
    return wrapper

def count_tokens(text):
    enc = tiktoken.encoding_for_model("gpt-3.5-turbo-16k")
    tokens = list(enc.encode(text))
    return len(tokens)

def extract_text_from_pdf(pdf_file):
    with pdfplumber.open(pdf_file) as pdf:
        text = " ".join(page.extract_text() for page in pdf.pages)
    return text

def split_pdf(pdf_file, num_pdfs):
    inputpdf = PdfReader(open(pdf_file, "rb"))
    inputpdf_name = str(pdf_file).replace('.pdf','')

    # Get the number of pages
    num_pages = int(len(inputpdf.pages))
    pages_per_pdf = int(np.floor(num_pages / num_pdfs))
    pages_last_pdf = int(num_pages - (pages_per_pdf * num_pdfs))
    for i in range(int(num_pdfs)):
        output = PdfWriter()
        if i == num_pdfs - 1:
            for j in range(pages_last_pdf):
                output.add_page(inputpdf.pages[pages_per_pdf * i + j])
        else:
            for j in range(pages_per_pdf):
                output.add_page(inputpdf.pages[pages_per_pdf * i + j])
        with open('{}_{}.pdf'.format(inputpdf_name,i), "wb") as outputStream:
            output.write(outputStream)

def generate_questions(prompt, pdf_file, temperature=1.0):
    formatted_prompt = [{"role": "system", "content": "You are a socratic medical school tutor that provides comprehensive learning questions."},
                        {"role": "user", "content": prompt}]
    remaining_tokens = MAX_TOKENS - count_tokens(" ".join([message["content"] for message in formatted_prompt])) - TOKEN_BUFFER

    if remaining_tokens < TOKEN_BUFFER:
        print(f"Warning! Input text is longer than model gpt-3.5-turbo-16k can support. Consider trimming input and trying again.")
        print(f"Current length: {count_tokens(prompt)}, recommended < {MAX_TOKENS - TOKEN_BUFFER}")
        # split PDF based on tokens
        num_pdfs = np.ceil(count_tokens(prompt) / (MAX_TOKENS - TOKEN_BUFFER)) + 1
        split_pdf(pdf_file, num_pdfs)
        os.remove(pdf_file)
        main(sys.argv[1]) # try again

    completions = openai.ChatCompletion.create(
        model="gpt-3.5-turbo-16k",
        messages=formatted_prompt,
        max_tokens=remaining_tokens,
        n=1,
        stop=None,
        temperature=temperature)

    return completions['choices'][0]['message']['content'].strip()

@handle_api_error
def define_objectives_from_pdf(pdf_file, temperature=1.0):
    text = extract_text_from_pdf(pdf_file)
    prompt = f"Generate a list of learning questions that comprehensively covers the most important information presented in the text below to understand the topics presented.\n\n{text}"
    generated_text = generate_questions(prompt, pdf_file, temperature=1.0)
    objectives = [line.strip() for line in generated_text.split("\n") if line.strip()]
    return objectives

@handle_api_error
def generate_embedding(obj, embedding_model="text-embedding-ada-002", embedding_encoding="cl100k_base"):

    # Set up the tokenizer
    encoding = tiktoken.get_encoding(embedding_encoding)

    # Generate the tokens and embeddings
    tokens = len(encoding.encode(obj))
    emb = get_embedding(obj, engine=embedding_model)

    return tokens, emb

def write_to_csv(csv_writer, output_prefix, objectives):
    n = 0
    for obj in objectives:
        obj_clean = re.sub(r'^\d+\.', '', obj).strip().lstrip('- ')
        remove_words = ['Summary', 'Learning', 'Objective', 'Guiding', 'Additional', 'Question']
        if len([word for word in remove_words if word in obj_clean]) < 2:
            n += 1
            tokens, emb = generate_embedding(obj)
            csv_writer.writerow([output_prefix,obj_clean,tokens,emb])
    print(f"Wrote {n} learning objectives to file for {output_prefix}")

def main(input_path):

    path = Path(input_path)
    output_prefix = path.stem
    output_file = output_prefix + "_learning_objectives.csv"

    if path.is_file():
        pdf_files = [input_path]
    elif path.is_dir():
        pdf_files = list(path.glob('*.pdf'))
    else:
        print("The provided path is not a valid file or directory.")
        sys.exit(1)

    if os.path.exists(output_file):
        obj_file_exists = True
        obj_dat = pd.read_csv(output_file)
        done_lec = obj_dat['name'].unique()
    else:
        obj_file_exists = False
        done_lec = []

    with open(output_file, 'a', newline='', encoding='utf-8') as csvfile:

        csv_writer = csv.writer(csvfile)

        if not obj_file_exists:
            csv_writer.writerow(['name', 'learning_objective','tokens','emb'])

        for pdf_file in pdf_files:
            if os.path.split(pdf_file)[-1].replace('.pdf','') not in done_lec:
                print('Working on',pdf_file)
                objectives = define_objectives_from_pdf(pdf_file)
                tag = Path(pdf_file).stem
                write_to_csv(csv_writer, tag, objectives)
            else:
                print('Already done with ',pdf_file)

if __name__ == "__main__":
    set_api_key()
    if len(sys.argv) != 2:
        print("Usage: make_learning_objectives.py <pdf_file_or_dir>")
        sys.exit(1)
    path = sys.argv[1]
    main(path)
