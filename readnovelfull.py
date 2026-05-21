# Novel Scraper and EPUB Converter with AJAX Support
# This script scrapes novels from a website that uses AJAX to load chapter links
# and converts the scraped content into an EPUB file.
# This is for https://readnovelfull.com site.

import requests
from bs4 import BeautifulSoup
import pandas as pd
from ebooklib import epub
import time
import argparse
import re

# Set up headers to mimic a browser request
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

# Function to get the list of chapter links (with AJAX support)
def get_chapter_links(novel_url):
    """
    Fetches chapter links from the novel's main page, including chapters loaded via AJAX.
    """
    response = requests.get(novel_url, headers=headers)
    soup = BeautifulSoup(response.content, 'html.parser')

    # Get the novel ID from the page (needed for AJAX requests)
    novel_id_tag = soup.select_one('#rating')
    novel_id = novel_id_tag['data-novel-id'] if novel_id_tag else None
    if not novel_id:
        print("Failed to find novel ID.")
        return []

    # Collect chapters loaded via AJAX
    ajax_url = f"https://readnovelfull.com/ajax/chapter-archive?novelId={novel_id}"
    response = requests.get(ajax_url, headers=headers)
    soup = BeautifulSoup(response.content, 'html.parser')

    # Find chapter links in the AJAX response
    chapters = []
    chapter_list = soup.select('.list-chapter a')  # Selector for chapter links in AJAX

    for chapter in chapter_list:
        chapter_url = "https://readnovelfull.com" + chapter['href']
        chapters.append(chapter_url)

    return chapters

# Function to scrape the content of each chapter
def scrape_chapter(chapter_url):
    """
    Scrapes the chapter title and content.
    """
    response = requests.get(chapter_url, headers=headers)
    soup = BeautifulSoup(response.content, 'html.parser')

    # Try to get the chapter title (within an 'a' tag inside an 'h2' tag)
    chapter_title_tag = soup.select_one('h2 a.chr-title span.chr-text')
    chapter_title = chapter_title_tag.get_text(strip=True) if chapter_title_tag else None

    # If the title isn't found, try a fallback method using regex
    if not chapter_title:
        print(f"Failed to find title for {chapter_url}")
        chapter_title = "Unknown Chapter"

    # Try to get the chapter content
    chapter_content_tag = soup.find('div', id='chr-content')
    if chapter_content_tag:
        chapter_content = chapter_content_tag.get_text(separator='\n').strip()
    else:
        print(f"Failed to find content for {chapter_url}")
        return None, None

    return chapter_title, chapter_content

# Function to get the author and title of the novel from the main page
def get_novel_info(novel_url):
    """
    Scrapes the title and author from the novel's main page.
    """
    response = requests.get(novel_url, headers=headers)
    soup = BeautifulSoup(response.content, 'html.parser')

    # Extract the title
    title_tag = soup.select_one('h3.title')
    novel_title = title_tag.get_text(strip=True) if title_tag else "Unknown Title"

    # Extract the author
    author_tag = soup.select_one('ul.info-meta a[href*="/authors/"]')
    author_name = author_tag.get_text(strip=True) if author_tag else "Unknown Author"

    return novel_title, author_name

# Function to scrape the entire novel
def scrape_novel(novel_url, limit=None, scrape_all=False):
    """
    Scrapes all chapters or up to a specified limit and saves to a DataFrame.
    """
    chapters = get_chapter_links(novel_url)
    novel_data = []

    # Determine how many chapters to scrape
    if scrape_all:
        limit = len(chapters)  # Set limit to total number of chapters if --all is used

    # Loop through the chapters and scrape the content
    for i, chapter_url in enumerate(chapters[:limit]):
        try:
            title, content = scrape_chapter(chapter_url)
            if title and content:
                print(f'Scraping chapter {i+1}: {title}')
                novel_data.append({'title': title, 'content': content})
            time.sleep(1)  # Sleep between requests to avoid hammering the server
        except Exception as e:
            print(f"Failed to scrape {chapter_url}: {e}")
            continue

    return pd.DataFrame(novel_data)

# Function to create an EPUB book from the scraped data
def create_epub(novel_df, novel_title, author_name, output_filename):
    """
    Creates an EPUB file from a DataFrame containing novel chapters.
    """
    # Initialize the EPUB book
    book = epub.EpubBook()

    # Set metadata
    book.set_identifier(novel_title.replace(" ", "_").lower())
    book.set_title(novel_title)
    book.set_language('en')
    book.add_author(author_name)

    # Loop through the CSV rows and add each chapter as a section in the EPUB
    for i, row in novel_df.iterrows():
        chapter = epub.EpubHtml(title=row['title'], file_name=f'chap_{i+1}.xhtml', lang='en')
        
        # Handle the chapter content and formatting
        chapter_content = row['content'].replace("\n", "<br>")  # Convert newlines to HTML breaks
        chapter.content = f'<h1>{row["title"]}</h1><p>{chapter_content}</p>'
        
        # Add chapter to the book
        book.add_item(chapter)
        book.spine.append(chapter)

    # Define the Table of Contents
    book.toc = tuple([epub.Link(f'chap_{i+1}.xhtml', row['title'], f'chap_{i+1}') for i, row in novel_df.iterrows()])
    
    # Add NCX and Navigation (for EPUB readers)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Define CSS style for the book
    style = 'BODY { font-family: Arial, sans-serif; }'
    nav_css = epub.EpubItem(uid="style_nav", file_name="style/nav.css", media_type="text/css", content=style)
    book.add_item(nav_css)

    # Save the EPUB file
    epub.write_epub(output_filename, book, {})

# Function to scrape a novel and convert it to an EPUB
def scrape_and_convert_to_epub(novel_url, limit=None, scrape_all=False):
    """
    Scrapes a novel and converts it to an EPUB file.
    """
    # Scrape the novel info (title and author)
    novel_title, author_name = get_novel_info(novel_url)
    print(f"Novel: {novel_title}, Author: {author_name}")

    # Scrape the novel chapters
    novel_df = scrape_novel(novel_url, limit=limit, scrape_all=scrape_all)

    # Generate the output filename based on the title
    output_epub = f'{novel_title.replace(" ", "_").lower()}.epub'
    
    # Create the EPUB file
    create_epub(novel_df, novel_title, author_name, output_epub)

    print(f"Scraping and EPUB conversion complete! EPUB saved as '{output_epub}'")

# Command-line argument parsing
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape a novel and convert it to EPUB.")
    parser.add_argument('novel_url', type=str, help='URL of the novel to scrape (e.g., https://readnovelfull.com/heaven-officials-blessing-novel.html)')
    parser.add_argument('--limit', type=int, default=None, help='Limit the number of chapters to scrape (default: scrape all chapters)')
    parser.add_argument('--all', action='store_true', help='Scrape all chapters (overrides limit)')

    args = parser.parse_args()
    novel_url = args.novel_url
    limit = args.limit
    scrape_all = args.all

    # Call the scraping and EPUB conversion function
    scrape_and_convert_to_epub(novel_url, limit=limit, scrape_all=scrape_all)
