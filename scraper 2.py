# This script scrapes chapters from a web novel site and compiles them into an EPUB file.
# It is for https://webnoveltranslations.com/ site.


import requests
from bs4 import BeautifulSoup
import time
import argparse
import re
import os
import ebooklib
from ebooklib import epub

# Set up headers to mimic a browser request
headers = {
    'User-Agent': 'Mozilla/50 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def scrape_chapter(url):
    """
    Scrapes the title and content from a single chapter URL.
    """
    print(f"Scraping chapter from: {url}")
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status() # Raise an exception for bad status codes
        soup = BeautifulSoup(response.content, 'html.parser')

        # Extract the chapter number from the URL to use as the title
        match = re.search(r'/chapter-(\d+)/$', url)
        title = f"Chapter {match.group(1)}" if match else "Unknown Title"

        # Find the content of the chapter
        content_div = soup.select_one('div.text-left')
        content_text = ""
        if content_div:
            # We are interested in the text within <p> tags
            paragraphs = content_div.find_all('p')
            content_text = '\n\n'.join(p.text.strip() for p in paragraphs)
        
        if not content_text:
            print(f"Warning: No content found for chapter at {url}")

        return {
            'title': title,
            'content': content_text
        }

    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL {url}: {e}")
        return None

def get_chapter_links(novel_url):
    """
    Fetches all chapter links by generating them from the URL pattern.
    """
    print("Fetching novel information...")
    response = requests.get(novel_url, headers=headers)
    soup = BeautifulSoup(response.content, 'html.parser')

    # Find the 'Read First' and 'Read Last' buttons to get the chapter range
    first_chapter_link_tag = soup.select_one('a#btn-read-last')
    last_chapter_link_tag = soup.select_one('a#btn-read-first')
    
    start_chapter = None
    end_chapter = None
    
    if first_chapter_link_tag:
        first_chapter_url = first_chapter_link_tag.get('href')
        if first_chapter_url:
            match = re.search(r'/chapter-(\d+)/$', first_chapter_url)
            if match:
                start_chapter = int(match.group(1))

    if last_chapter_link_tag:
        last_chapter_url = last_chapter_link_tag.get('href')
        if last_chapter_url:
            match = re.search(r'/chapter-(\d+)/$', last_chapter_url)
            if match:
                end_chapter = int(match.group(1))

    if not start_chapter or not end_chapter:
        print("Failed to find chapter range.")
        return []
    
    print(f"Starting chapter found: {start_chapter}")
    print(f"Ending chapter found: {end_chapter}")

    # Generate the URLs directly.
    base_url = novel_url.rstrip('/')
    chapters = []
    for chapter_num in range(start_chapter, end_chapter + 1):
        chapters.append(f"{base_url}/chapter-{chapter_num}/")
        
    print(f"Generated {len(chapters)} chapter links.")
    
    return chapters

def get_novel_title(novel_url):
    """
    Scrapes the novel's title from the main page.
    """
    try:
        response = requests.get(novel_url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        title_tag = soup.select_one('h1.post-title')
        if title_tag:
            return title_tag.text.strip()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching novel title: {e}")
    return "Unknown Novel"


def create_epub(novel_data, novel_title, novel_author, output_filename):
    """
    Creates an EPUB file from the scraped novel data.
    """
    print(f"\nCreating EPUB file: {output_filename}...")
    book = epub.EpubBook()

    # Set metadata
    book.set_identifier('id123456')
    book.set_title(novel_title)
    book.set_language('en')
    book.add_author(novel_author)

    chapters = []
    for i, chapter_data in enumerate(novel_data):
        # Create an EPUB chapter object (EpubHtml)
        c = epub.EpubHtml(title=chapter_data['title'], file_name=f'chap_{i+1}.xhtml', lang='en')
        
        # Format the content as basic HTML
        html_content = f"<h1>{chapter_data['title']}</h1>\n"
        html_content += "".join(f"<p>{line}</p>" for line in chapter_data['content'].split('\n\n'))
        
        c.content = html_content
        
        book.add_item(c)
        chapters.append(c)

    # Define the spine and table of contents
    book.toc = tuple(chapters)
    book.spine = ['nav'] + chapters

    # Add default NCX and Nav file
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Write the EPUB file
    epub.write_epub(output_filename, book, {})
    print(f"EPUB file '{output_filename}' created successfully.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape a novel and save as EPUB.")
    parser.add_argument('novel_url', type=str, help='URL of the novel to scrape.')
    parser.add_argument('chapters_to_scrape', type=str, help='Number of chapters to scrape from the start, or "all" for all chapters.')
    args = parser.parse_args()
    
    novel_title = get_novel_title(args.novel_url)
    novel_author = "Web Novel Scraper"
    
    chapter_urls = get_chapter_links(args.novel_url)
    
    if chapter_urls:
        scraped_chapters = []
        
        if args.chapters_to_scrape.lower() == 'all':
            urls_to_scrape = chapter_urls
        else:
            try:
                num_chapters = int(args.chapters_to_scrape)
                if num_chapters <= 0:
                    print("Please provide a positive number of chapters.")
                    exit()
                urls_to_scrape = chapter_urls[:num_chapters]
            except ValueError:
                print("Invalid input for number of chapters. Please use a number or 'all'.")
                exit()
        
        print(f"\nStarting to scrape {len(urls_to_scrape)} chapters...")
        for url in urls_to_scrape:
            chapter_data = scrape_chapter(url)
            if chapter_data:
                scraped_chapters.append(chapter_data)
        
        if scraped_chapters:
            output_filename = f"{novel_title.replace(' ', '_')}.epub"
            create_epub(scraped_chapters, novel_title, novel_author, output_filename)
    else:
        print("\nFailed to get chapter links. Exiting.")
