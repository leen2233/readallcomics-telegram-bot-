import io
import pprint
import re
from enum import Enum
from typing import Dict, List

import cloudscraper
from bs4 import BeautifulSoup as BS
from PIL import Image


class Status(Enum):
    """
    Enum for the different steps
    """

    DOWNLOADING = "Downloading"
    CROPPING = "Cropping"
    ADDING_PAGES = "Adding Pages"
    EXPORTING = "Exporting PDF"
    COMPLETE = "Complete!"


def get_status_length() -> int:
    """
    returns length of the longest Status string
    """
    res = 0
    for status in Status:
        res = max(res, len(status.value))
    return res

scraper = cloudscraper.create_scraper()


__author__ = "nighmared"
__version__ = 1.21


DEBUG = False  # makes it more verbose
PDF_H = 300  # Height of resulting PDF
PDF_W = 200  # Width of resulting PDF
# For most comics i have seen an aspect ratio of 2:3 seems to be a good call

PROGRESS_BAR_LEN = 50  # lenght of the progress bar that is displayed
STATUS_LEN = (
    get_status_length() + 1
)  # How much space must be accounted for the status in the progress bar
NUM_STEPS = len(Status)  # Number of steps the program goes through
STEP_SIZE = PROGRESS_BAR_LEN // NUM_STEPS  # equal length parts for the status bar


def get_comic_images(entry: dict) -> dict:
    url = entry.get("url", "").strip()
    name = entry.get("name", "").strip()
    base = scraper.get(url)
    base.close()
    soup = BS(base.content, "html.parser")
    pages = soup.select("center p img")
    urls = []

    for page in pages:
        source = page["src"]
        if isinstance(source, list):
            raise AttributeError("Image can't have more than one source")
        urls.append(source)

    return {"name": name, "urls": urls}


def search_comics(query: str):
    """
    Search for comics on readallcomics.com

    Args:
        query (str): Search term for comics
        nonce (str): Security nonce (default provided)

    Returns:
        Dict containing search results with title and URL for each comic
    """

    # URL and headers
    url = f"https://readallcomics.com/?story={query}&s=&type=comic"

    try:
        # Make the request
        response = scraper.post(url, timeout=10)
        response.raise_for_status()

        # Parse the HTML response
        html_content = response.text.strip('"').replace("\\", "")  # Remove surrounding quotes
        # Extract links and titles using regex
        link_pattern = r'<a href="([^"]*)"[^>]*>([^<]*)</a>'
        matches = re.findall(link_pattern, html_content)
        # Process results
        results = []
        for url, title in matches:
            # Clean up the URL (unescape HTML entities)
            clean_title = title.strip()
            if "/category" in url:
                results.append({
                    'title': clean_title,
                    'url': url
                })

        return {
            'query': query,
            'total_results': len(results),
            'results': results
        }

    except Exception as e:
        return {
            'query': query,
            'error': f'Parsing failed: {str(e)}',
            'total_results': 0,
            'results': []
        }

def print_results(results: Dict) -> None:
    """Pretty print the search results"""
    print(f"\nSearch Query: '{results['query']}'")
    print(f"Total Results: {results['total_results']}")

    if 'error' in results:
        print(f"Error: {results['error']}")
        return

    print("\nResults:")
    print("-" * 80)

    for i, result in enumerate(results['results'], 1):
        print(f"{i:2d}. {result['title']}")
        print(f"    URL: {result['url']}")
        print()

def get_comic_details(url):
    response = scraper.get(url)
    soup = BS(response.content, "html.parser")

    chapters = []
    genres_element = publisher_element = title = genres = publisher = description = image = None

    title_element = soup.select_one("center div h1 b")
    image_element = soup.select_one("center p img")
    description_element = str(soup.select_one("div.b"))

    info = soup.select_one("center div div p")
    chapters_element = soup.find(attrs={"class": "list-story"})

    if chapters_element:
        links = chapters_element.find_all("a")
        for link in links:
            name = link.get_text(strip=True)
            url = link["href"]
            chapters.append({"url": url, "name": name})

    if info:
        genres_element = info.find_next("strong")
        if genres_element:
            publisher_element = genres_element.find_next("strong")

    if title_element:
        title = title_element.text
    if genres_element:
        genres = genres_element.text.split(", ")
    if publisher_element:
        publisher = publisher_element.text
    if image_element:
        image = image_element.get("src")

    match = re.search(r'</span><br/>(.*?)<br/>', description_element, re.DOTALL)
    if match:
        description = match.group(1).strip()

    return {
        "title": title,
        "genres": genres,
        "publisher": publisher,
        "desccription": description,
        "chapters": chapters,
        "image": image
    }


def home_page(page=1):
    url = f"https://readallcomics.com/page/{page}/"
    response = scraper.get(url)
    soup = BS(response.content, "html.parser")

    divs = soup.find_all('div', {'id': lambda x: x and x.startswith('post-'), 'class': lambda x: x and 'post-' in x}) # type: ignore
    for div in divs:
        url = div.select_one("a").get("href")
        image = div.select_one("img").get("src")
        name = div.find("a", attrs={"class": "front-link"})
        date = div.select_one("center span").text
        print(url, image, name.text, date)

def get_page_count():
    url = "https://readallcomics.com/"
    response = scraper.get(url)
    soup = BS(response.content, "html.parser")

    numbers = soup.find_all('a', {"class": "page-numbers"}) # type: ignore
    for div in divs:
        url = div.select_one("a").get("href")
        image = div.select_one("img").get("src")
        name = div.find("a", attrs={"class": "front-link"})
        date = div.select_one("center span").text
        print(url, image, name.text, date)


def get_comic_page(url):
    response = scraper.get(url)
    html_content = response.text.strip('"').replace("\\", "")

    link_pattern = r'<a href="(https://readallcomics\.com/category/[\w-]+/)"[^>]*>([^<]*)</a>'
    matches = re.findall(link_pattern, html_content)
    print(matches)


def download_images_to_pdf(urls: List[str], output_filename: str = "output.pdf") -> str:
    """
    Download images from URLs and convert them to an A4-sized PDF.

    Args:
        urls (List[str]): List of image URLs to download
        output_filename (str): Name of the output PDF file (default: "output.pdf")

    Returns:
        str: Path to the generated PDF file
    """
    # A4 size in pixels at 300 DPI (high quality)
    # A4: 210mm x 297mm
    # At 300 DPI: 2480 x 3508 pixels
    A4_WIDTH = 2480
    A4_HEIGHT = 3508

    downloaded_images = []

    for i, url in enumerate(urls, 1):
        try:
            print(f"Downloading image {i}/{len(urls)}: {url}")
            response = scraper.get(url, timeout=30)
            response.raise_for_status()

            img = Image.open(io.BytesIO(response.content))

            # Convert to RGB if necessary (for PDF compatibility)
            if img.mode != 'RGB':
                img = img.convert('RGB')

            # Resize to fit A4 while maintaining aspect ratio
            img.thumbnail((A4_WIDTH, A4_HEIGHT), Image.Resampling.LANCZOS)
            downloaded_images.append(img)

        except Exception as e:
            print(f"Error downloading image {i}: {e}")
            continue

    if not downloaded_images:
        raise ValueError("No images were successfully downloaded")

    # Save as PDF
    print(f"Creating PDF with {len(downloaded_images)} pages...")
    downloaded_images[0].save(
        output_filename,
        save_all=True,
        append_images=downloaded_images[1:],
        resolution=300.0,
        quality=95
    )

    print(f"PDF saved to: {output_filename}")
    return output_filename


# Example usage
if __name__ == "__main__":
    comic_url = input("Enter comic URL: ").strip()

    if not comic_url:
        print("No URL provided. Exiting.")
        exit(1)

    comic_name = input("Enter filename to save (without extension): ").strip() or "comic"

    # Add .pdf extension if not present
    if not comic_name.lower().endswith(".pdf"):
        comic_name += ".pdf"

    print(f"\nFetching comic images from: {comic_url}")
    urls = get_comic_images({"url": comic_url, "name": comic_name})

    if not urls.get("urls"):
        print("No images found.")
        exit(1)

    print(f"Found {len(urls['urls'])} pages. Downloading...\n")
    download_images_to_pdf(urls["urls"], comic_name)
