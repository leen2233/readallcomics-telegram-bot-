"""
PDF Booklet Converter for Comic Downloader
Implements 2-up saddle stitch booklet format with configurable margins
"""
import math
from typing import List, Tuple, Optional
from enum import Enum

from pypdf import PdfReader, PdfWriter, Transformation, PageObject


class FlipOption(Enum):
    """Printer duplex binding options"""
    LONG_EDGE = "long_edge"  # Standard portrait binding (like books)
    SHORT_EDGE = "short_edge"  # Landscape/calendar-style binding


class BookletConverter:
    """
    Convert PDF to 2-up saddle stitch booklet format.

    This takes a standard PDF and imposes it for printing as a booklet:
    - Pages are rearranged so they print in correct order when folded
    - 2 pages per sheet (front and back)
    - Supports configurable margins
    - Supports both long-edge and short-edge duplex printing
    """

    # A4 size in points (1 point = 1/72 inch)
    A4_WIDTH = 595.28
    A4_HEIGHT = 841.89

    def __init__(
        self,
        margin_top: float = 10,
        margin_bottom: float = 10,
        margin_left: float = 10,
        margin_right: float = 10,
        flip_option: FlipOption = FlipOption.LONG_EDGE
    ):
        """
        Initialize booklet converter.

        Args:
            margin_top: Top margin in mm
            margin_bottom: Bottom margin in mm
            margin_left: Left margin in mm
            margin_right: Right margin in mm
            flip_option: LONG_EDGE for standard portrait, SHORT_EDGE for landscape
        """
        # Convert mm to points (1 mm = 2.83465 points)
        mm_to_pt = 2.83465

        self.margin_top_pt = margin_top * mm_to_pt
        self.margin_bottom_pt = margin_bottom * mm_to_pt
        self.margin_left_pt = margin_left * mm_to_pt
        self.margin_right_pt = margin_right * mm_to_pt
        self.flip_option = flip_option

    def create_booklet(
        self,
        input_pdf_path: str,
        output_pdf_path: str,
        progress_callback: Optional[callable] = None
    ) -> None:
        """
        Convert PDF to 2-up saddle stitch booklet format.

        Args:
            input_pdf_path: Path to input PDF file
            output_pdf_path: Path to save booklet PDF
            progress_callback: Optional callback for progress updates
        """
        # Read input PDF
        reader = PdfReader(input_pdf_path)
        num_pages = len(reader.pages)

        if progress_callback:
            progress_callback(f"Processing {num_pages} pages...")

        # Calculate total pages needed (must be multiple of 4)
        total = num_pages
        while total % 4 != 0:
            total += 1  # Add blank pages

        # Calculate page dimensions
        page_width = self.A4_WIDTH - self.margin_left_pt - self.margin_right_pt
        page_height = self.A4_HEIGHT / 2

        writer = PdfWriter()

        # Create booklet imposition
        for s in range(total // 4):
            # Calculate page indices for this signature
            # For 2-up saddle stitch booklet:
            # Front: [last_page, first_page]
            # Back:  [second_page, second_last_page]

            if self.flip_option == FlipOption.LONG_EDGE:
                # Standard long-edge binding
                LF = total - 1 - 2 * s  # left front
                RF = 2 * s              # right front
                LB = 2 * s + 1          # left back
                RB = total - 2 - 2 * s  # right back
            else:
                # Short-edge binding
                LF = 2 * s              # left front
                RF = total - 1 - 2 * s  # right front
                LB = total - 2 - 2 * s  # left back
                RB = 2 * s + 1          # right back

            # Create front sheet
            front = writer.add_blank_page(width=self.A4_WIDTH, height=self.A4_HEIGHT)
            self._add_page_side(front, reader, num_pages, total, LF, "top", page_width, page_height)
            self._add_page_side(front, reader, num_pages, total, RF, "bottom", page_width, page_height)

            # Create back sheet
            back = writer.add_blank_page(width=self.A4_WIDTH, height=self.A4_HEIGHT)
            self._add_page_side(back, reader, num_pages, total, LB, "top", page_width, page_height)
            self._add_page_side(back, reader, num_pages, total, RB, "bottom", page_width, page_height)

            if progress_callback:
                progress_callback(f"Created sheet {s + 1}/{total // 4}")

        # Write output
        with open(output_pdf_path, "wb") as output_file:
            writer.write(output_file)

        if progress_callback:
            progress_callback("Booklet created successfully!")

    def _add_page_side(
        self,
        output_page: PageObject,
        reader: PdfReader,
        num_pages: int,
        total: int,
        page_index: int,
        position: str,
        content_width: float,
        content_height: float
    ) -> None:
        """
        Add a source page to one side of the output page.

        Args:
            output_page: Destination page object
            reader: PDF reader for source pages
            num_pages: Actual number of pages in source PDF
            total: Total pages including blanks (multiple of 4)
            page_index: Index of page to add (0-based)
            position: "top" or "bottom" half of output page
            content_width: Width of content area
            content_height: Height of each half-page
        """
        # Check if this is a blank page (beyond actual pages)
        if page_index < 0 or page_index >= num_pages:
            return

        if page_index >= total:
            return  # This is an extra blank page

        # Get source page
        src = reader.pages[page_index]

        # Get source page dimensions
        src_mbox = src.mediabox
        src_width = float(src_mbox.width)
        src_height = float(src_mbox.height)

        # For booklet, we need to rotate the page 90 degrees
        # Swap width/height for rotation calculation
        rotated_src_width = src_height  # After 90° rotation
        rotated_src_height = src_width

        # Calculate scale to fit content area (rotated dimensions)
        scale_x = content_width / rotated_src_width
        scale_y = content_height / rotated_src_height
        scale = min(scale_x, scale_y)  # Maintain aspect ratio

        # Calculate scaled dimensions (after rotation and scale)
        scaled_width = rotated_src_width * scale
        scaled_height = rotated_src_height * scale

        # Calculate centering offsets
        x_offset = (content_width - scaled_width) / 2
        y_offset = (content_height - scaled_height) / 2

        # Calculate absolute position on output page
        if position == "top":
            x = self.margin_left_pt + x_offset
            y = (self.A4_HEIGHT / 2) - self.margin_top_pt - scaled_height - y_offset
        else:  # bottom
            x = self.margin_left_pt + x_offset
            y = self.A4_HEIGHT - self.margin_bottom_pt - scaled_height - y_offset

        # Create transformation: rotate 90° clockwise, scale, then translate
        # For a 90° clockwise rotation:
        # - The top-left corner (0, h) rotates to (0, 0) relative to page origin
        # - After rotation, the point that was at height becomes the new x offset
        #
        # To position the top-left corner at (x, y), we translate by (x, y)
        # The y position is relative to the rotated page's top edge

        tr = Transformation().rotate(90).scale(scale, scale).translate(x, y)
        output_page.merge_transformed_page(src, tr)

    @staticmethod
    def get_page_count(input_pdf_path: str) -> int:
        """Get the number of pages in a PDF file"""
        reader = PdfReader(input_pdf_path)
        return len(reader.pages)

    @staticmethod
    def validate_pdf(input_pdf_path: str) -> bool:
        """Validate that a file is a valid PDF"""
        try:
            reader = PdfReader(input_pdf_path)
            return len(reader.pages) > 0
        except Exception:
            return False


# Convenience function for quick conversion
def convert_to_booklet(
    input_path: str,
    output_path: str,
    margins: float = 10,
    flip_option: FlipOption = FlipOption.LONG_EDGE,
    progress_callback: Optional[callable] = None
) -> None:
    """
    Quick function to convert PDF to booklet with uniform margins.

    Args:
        input_path: Input PDF path
        output_path: Output PDF path
        margins: Margin in mm (applied to all sides)
        flip_option: LONG_EDGE or SHORT_EDGE
        progress_callback: Optional progress callback
    """
    converter = BookletConverter(
        margin_top=margins,
        margin_bottom=margins,
        margin_left=margins,
        margin_right=margins,
        flip_option=flip_option
    )
    converter.create_booklet(input_path, output_path, progress_callback)
