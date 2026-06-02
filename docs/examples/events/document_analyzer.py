"""
DocumentAnalyzer - A self-contained class for classifying and extracting fields from ID documents.

This module provides deterministic document analysis using PDF417 barcodes, MRZ parsing,
and OCR heuristics. No LLMs or external network calls are required.
"""

import io
import logging
import re
import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageEnhance, ImageOps
except ImportError:
    raise ImportError("Pillow is required. Install with: pip install Pillow")

try:
    from pdf2image import convert_from_path
except ImportError:
    raise ImportError("pdf2image is required. Install with: pip install pdf2image")

try:
    from passporteye import read_mrz
except ImportError:
    raise ImportError("passporteye is required. Install with: pip install passporteye")

try:
    from paddleocr import PaddleOCR
except ImportError:
    raise ImportError("paddleocr is required. Install with: pip install paddleocr")

try:
    import zxingcpp

    _ZXING_AVAILABLE = True
except ImportError:
    _ZXING_AVAILABLE = False


class DocumentAnalyzer:
    """
    Analyzes ID documents (PNG/JPG/GIF/PDF) to classify type and extract fields.

    Detection order: PDF417 barcode → MRZ → OCR heuristics.
    No external network calls. All processing is local and deterministic.
    """

    def __init__(self) -> None:
        """Initialize the DocumentAnalyzer."""
        self._ocr_engine: PaddleOCR | None = None

    def _get_ocr_engine(self) -> PaddleOCR:
        """Lazy initialization of PaddleOCR engine."""
        if self._ocr_engine is None:
            # Newer versions of PaddleOCR don't support show_log parameter
            try:
                self._ocr_engine = PaddleOCR(
                    use_angle_cls=True, lang="en", show_log=False
                )
            except (ValueError, TypeError):
                # Fallback for newer versions that don't support show_log
                try:
                    self._ocr_engine = PaddleOCR(use_angle_cls=True, lang="en")
                except Exception as e:
                    logger.warning(f"Failed to initialize PaddleOCR: {e}")
                    raise
        return self._ocr_engine

    def analyze(self, inp: str | bytes, pdf_pages: int = 1) -> dict[str, Any]:
        """
        Analyze a document and extract classification and fields.

        Args:
            inp: Path to file (PNG/JPG/GIF/PDF) or raw bytes
            pdf_pages: Maximum number of PDF pages to process (default: 1)

        Returns:
            dict with keys:
                - document_type: "passport" | "drivers_license" | "national_id" |
                                 "social_security_card" | "unknown"
                - attributes: dict of extracted fields
                - confidences: dict mapping field/source to confidence score
                - signals: dict with detection metadata (barcode_symbology, mrz_raw, etc.)
        """
        logger.info("Starting document analysis")
        result: dict[str, Any] = {
            "document_type": "unknown",
            "attributes": {},
            "confidences": {},
            "signals": {},
        }

        try:
            # Convert input to JPEG images
            logger.debug(f"Converting input to JPEG images (pdf_pages={pdf_pages})")
            page_count = 0
            for img_path in self._iter_pages_to_jpegs(inp, pdf_pages):
                page_count += 1
                logger.debug(f"Processing page {page_count}: {img_path}")
                try:
                    # Step 1: Try PDF417 barcode (AAMVA)
                    logger.debug("Step 1: Attempting PDF417 barcode detection...")
                    barcode_result = self._decode_pdf417(img_path)
                    if barcode_result:
                        logger.debug(f"Barcode found: {barcode_result[:50]}...")
                        aamva_data = self._parse_aamva(barcode_result)
                        if aamva_data:
                            logger.info(
                                f"Successfully extracted AAMVA data: {len(aamva_data)} fields"
                            )
                            result["document_type"] = "drivers_license"
                            result["attributes"] = aamva_data
                            result["confidences"] = {"barcode": 0.95}
                            result["signals"] = {
                                "barcode_symbology": "PDF417",
                                "barcode_raw_present": True,
                            }
                            return result
                        else:
                            logger.debug("Barcode found but not in AAMVA format")
                    else:
                        logger.debug("No PDF417 barcode detected")

                    # Step 2: Try MRZ parsing
                    logger.debug("Step 2: Attempting MRZ parsing...")
                    mrz_result = self._parse_mrz(img_path)
                    if mrz_result:
                        doc_type = mrz_result.pop("document_type", "unknown")
                        valid_score = mrz_result.pop("mrz_valid_score", 0.0)
                        attributes = mrz_result.get("attributes", {})
                        logger.debug(
                            f"MRZ result: type={doc_type}, score={valid_score}, attributes={len(attributes)}"
                        )

                        # Accept MRZ result if we have a valid score OR if we extracted attributes
                        if valid_score > 0 or attributes:
                            logger.info(
                                f"Successfully extracted MRZ data: {len(attributes)} fields, score={valid_score}"
                            )
                            result["document_type"] = doc_type
                            result["attributes"] = attributes
                            result["confidences"] = {"mrz_valid_score": valid_score}
                            result["signals"] = {
                                "mrz_raw": mrz_result.get("mrz_raw", ""),
                            }
                            # Return result even with low score if we have attributes
                            return result
                        else:
                            logger.debug(
                                "MRZ found but invalid score and no attributes extracted"
                            )
                    else:
                        logger.debug("No MRZ detected")

                    # Step 3: OCR heuristics (only if barcode and MRZ failed)
                    if not result["attributes"]:
                        logger.debug("Step 3: Attempting OCR text extraction...")
                        ocr_text = self._ocr_text(img_path)
                        if ocr_text:
                            logger.debug(f"OCR extracted {len(ocr_text)} characters")
                            logger.debug(f"OCR text preview: {ocr_text[:200]}...")
                            doc_type, ocr_attrs = self._infer_from_ocr(ocr_text)
                            logger.debug(
                                f"OCR inference: type={doc_type}, attributes={len(ocr_attrs)}"
                            )
                            if doc_type != "unknown":
                                logger.info(
                                    f"Successfully extracted OCR data: {len(ocr_attrs)} fields"
                                )
                                result["document_type"] = doc_type
                                result["attributes"] = ocr_attrs
                                result["confidences"] = {"ocr": 0.6}
                                result["signals"] = {
                                    "ocr_text_excerpt": ocr_text[:500],
                                }
                                return result
                            else:
                                logger.debug(
                                    "OCR text found but document type not identified"
                                )
                                result["confidences"] = {"ocr": 0.2}
                        else:
                            logger.debug("No OCR text extracted")

                except Exception as e:
                    logger.error(
                        f"Error processing page {page_count}: {str(e)}", exc_info=True
                    )
                    # Continue to next page on error
                    continue

        except Exception as e:
            logger.error(f"Error in document analysis: {str(e)}", exc_info=True)
            # Return unknown on any failure
            pass

        logger.warning(
            f"Analysis complete but no data extracted. Final result: {result}"
        )
        return result

    def _iter_pages_to_jpegs(self, inp: str | bytes, max_pages: int) -> Iterable[str]:
        """
        Convert input (path or bytes) to JPEG image paths.

        Args:
            inp: File path or raw bytes
            max_pages: Maximum number of pages to process (for PDFs)

        Yields:
            str: Path to temporary JPEG file
        """
        temp_files: list[str] = []

        try:
            if isinstance(inp, bytes):
                # Write bytes to temp file first
                with tempfile.NamedTemporaryFile(delete=False, suffix=".tmp") as tmp:
                    tmp.write(inp)
                    inp_path = tmp.name
                temp_files.append(inp_path)
            else:
                inp_path = inp

            path = Path(inp_path)
            suffix = path.suffix.lower()

            # Handle GIF - extract first frame
            if suffix == ".gif":
                img = Image.open(inp_path)
                # Convert to RGB if necessary
                if img.mode != "RGB":
                    img = img.convert("RGB")
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    img.save(tmp.name, "JPEG", quality=95)
                    temp_files.append(tmp.name)
                    yield tmp.name

            # Handle PDF - convert pages to images
            elif suffix == ".pdf":
                images = convert_from_path(
                    inp_path, dpi=300, first_page=1, last_page=max_pages
                )
                for img in images:
                    with tempfile.NamedTemporaryFile(
                        delete=False, suffix=".jpg"
                    ) as tmp:
                        img.save(tmp.name, "JPEG", quality=95)
                        temp_files.append(tmp.name)
                        yield tmp.name

            # Handle image files (PNG, JPG, JPEG)
            elif suffix in (".png", ".jpg", ".jpeg"):
                img = Image.open(inp_path)
                # Convert to RGB if necessary
                if img.mode != "RGB":
                    img = img.convert("RGB")
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    img.save(tmp.name, "JPEG", quality=95)
                    temp_files.append(tmp.name)
                    yield tmp.name

            else:
                # Unknown format, try to open as image anyway
                try:
                    img = Image.open(inp_path)
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    with tempfile.NamedTemporaryFile(
                        delete=False, suffix=".jpg"
                    ) as tmp:
                        img.save(tmp.name, "JPEG", quality=95)
                        temp_files.append(tmp.name)
                        yield tmp.name
                except Exception:
                    pass

        finally:
            # Cleanup: only delete temp files we created from bytes
            if isinstance(inp, bytes):
                for tmp_file in temp_files:
                    try:
                        Path(tmp_file).unlink(missing_ok=True)
                    except Exception:
                        pass

    def _decode_pdf417(self, img_path: str) -> str | None:
        """
        Decode PDF417 barcode from image using ZXing.

        First tries the zxing-cpp Python package, then falls back to CLI tools.

        Args:
            img_path: Path to JPEG image

        Returns:
            Decoded barcode payload as string, or None if not found/unavailable
        """
        logger.debug(f"Attempting to decode PDF417 barcode from {img_path}")
        # Try zxing-cpp Python package first (preferred)
        if _ZXING_AVAILABLE:
            logger.debug("Using zxing-cpp Python package")
            try:
                # Read image and convert to bytes
                with Image.open(img_path) as img:
                    # Convert to RGB if necessary
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    # Save to bytes buffer
                    with io.BytesIO() as buffer:
                        img.save(buffer, format="JPEG", quality=95)
                        image_bytes = buffer.getvalue()

                # Decode barcodes
                results = zxingcpp.read_barcodes(image_bytes)

                if not results:
                    logger.debug("No barcodes found by zxing-cpp")
                    return None

                logger.debug(f"Found {len(results)} barcode(s) using zxing-cpp")

                # Look for PDF417 barcode specifically
                try:
                    for result in results:
                        # Check if format is PDF417 (handle both enum and string comparison)
                        format_str = str(result.format).upper()
                        if "PDF417" in format_str or (
                            hasattr(zxingcpp, "BarcodeFormat")
                            and result.format == zxingcpp.BarcodeFormat.PDF417
                        ):
                            logger.debug(f"Found PDF417 barcode: {result.text[:50]}...")
                            return result.text
                except (AttributeError, TypeError) as e:
                    logger.debug(f"Error checking barcode format: {e}")
                    # If format checking fails, continue to return first result
                    pass

                # If no PDF417 found but other barcodes exist, return first one
                # (in case format detection is imperfect or we need any barcode)
                logger.debug(
                    f"Using first barcode (not PDF417): {results[0].text[:50]}..."
                )
                return results[0].text
            except Exception as e:
                logger.debug(f"zxing-cpp failed: {e}")
                # Fall through to CLI fallback
                pass

        # Fallback to CLI tools if Python package not available or failed
        logger.debug("Falling back to CLI tools")
        zxing_commands = [
            (["zxing", "--raw", img_path], "zxing"),
            (["zxing-cpp", "--raw", img_path], "zxing-cpp"),
            (["zbarimg", "--raw", "-1", img_path], "zbarimg"),
        ]

        for cmd, binary_name in zxing_commands:
            try:
                logger.debug(f"Trying CLI tool: {binary_name}")
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    logger.debug(
                        f"Found barcode using {binary_name}: {result.stdout.strip()[:50]}..."
                    )
                    return result.stdout.strip()
                else:
                    logger.debug(f"{binary_name} returned code {result.returncode}")
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                logger.debug(f"{binary_name} not available: {e}")
                continue
            except Exception as e:
                logger.debug(f"Error running {binary_name}: {e}")
                continue

        logger.debug("No barcodes found with any method")
        return None

    def _parse_aamva(self, payload: str) -> dict[str, Any] | None:
        """
        Parse AAMVA format from PDF417 barcode payload.

        Args:
            payload: Raw barcode payload string

        Returns:
            dict of extracted attributes, or None if not AAMVA format
        """
        # Check for AAMVA header (ANSI or AAMVA)
        if "ANSI" not in payload and "AAMVA" not in payload:
            return None

        attributes: dict[str, Any] = {}

        # AAMVA uses field separators (0x1E) and subfield separators (0x1F)
        # Tags are 3 letters followed by data
        # Common pattern: TAG[data] or TAG[length][data]

        # More flexible tag matching - handle both with and without length prefix
        tag_patterns = {
            "DAQ": r"DAQ(\d{2})([^\x1e\x1f]+)",  # License number (with length prefix)
            "DCS": r"DCS([^\x1e\x1f]+)",  # Surname
            "DAC": r"DAC([^\x1e\x1f]+)",  # First name
            "DAD": r"DAD([^\x1e\x1f]+)",  # Middle name
            "DCT": r"DCT([^\x1e\x1f]+)",  # Given names (combined)
            "DBB": r"DBB(\d{8})",  # Date of birth (MMDDYYYY)
            "DBA": r"DBA(\d{8})",  # Expiration date (MMDDYYYY)
            "DBC": r"DBC([12])",  # Sex (1=M, 2=F)
            "DAG": r"DAG([^\x1e\x1f]+)",  # Address line 1
            "DAI": r"DAI([^\x1e\x1f]+)",  # City
            "DAJ": r"DAJ([A-Z]{2})",  # State (2-letter code)
            "DAK": r"DAK(\d{5,9})",  # Postal code
        }

        for tag, pattern in tag_patterns.items():
            match = re.search(pattern, payload)
            if match:
                try:
                    if tag == "DAQ":
                        # Format: DAQ + 2-digit length + value
                        length_str = match.group(1)
                        length = int(length_str)
                        value = match.group(2)[:length].strip()
                        if value:
                            attributes["license_number"] = value
                    elif tag == "DBB":
                        # MMDDYYYY -> YYYY-MM-DD
                        dob_str = match.group(1)
                        if len(dob_str) == 8:
                            month = int(dob_str[0:2])
                            day = int(dob_str[2:4])
                            year = int(dob_str[4:8])
                            # Basic validation
                            if (
                                1 <= month <= 12
                                and 1 <= day <= 31
                                and 1900 <= year <= 2100
                            ):
                                attributes["date_of_birth"] = (
                                    f"{year:04d}-{month:02d}-{day:02d}"
                                )
                    elif tag == "DBA":
                        # MMDDYYYY -> YYYY-MM-DD
                        exp_str = match.group(1)
                        if len(exp_str) == 8:
                            month = int(exp_str[0:2])
                            day = int(exp_str[2:4])
                            year = int(exp_str[4:8])
                            # Basic validation
                            if (
                                1 <= month <= 12
                                and 1 <= day <= 31
                                and 1900 <= year <= 2100
                            ):
                                attributes["expiration_date"] = (
                                    f"{year:04d}-{month:02d}-{day:02d}"
                                )
                    elif tag == "DBC":
                        # 1 -> M, 2 -> F
                        sex_code = match.group(1)
                        attributes["sex"] = "M" if sex_code == "1" else "F"
                    elif tag == "DAJ":
                        state = match.group(1).strip()
                        if len(state) == 2:
                            attributes["state"] = state
                    elif tag == "DAK":
                        postal = match.group(1).strip()
                        if 5 <= len(postal) <= 9:
                            attributes["postal_code"] = postal
                    else:
                        # Other tags: extract value directly
                        value = match.group(1).strip()
                        if value:
                            if tag == "DCS":
                                attributes["surname"] = value
                            elif tag == "DAC":
                                attributes["first_name"] = value
                            elif tag == "DAD":
                                attributes["middle_name"] = value
                            elif tag == "DCT":
                                attributes["given_names"] = value
                            elif tag == "DAG":
                                attributes["address1"] = value
                            elif tag == "DAI":
                                attributes["city"] = value
                except (ValueError, IndexError, AttributeError):
                    # Skip invalid matches
                    continue

        # If we extracted any attributes, return them
        return attributes if attributes else None

    def _preprocess_image_for_mrz(self, img_path: str) -> list[str]:
        """
        Preprocess image to improve MRZ detection.
        Creates multiple variants with different enhancements.

        Args:
            img_path: Path to original image

        Returns:
            List of paths to preprocessed image variants
        """
        variants: list[str] = []
        try:
            with Image.open(img_path) as img:
                # Convert to RGB if necessary
                if img.mode != "RGB":
                    img = img.convert("RGB")

                width, height = img.size

                # Variant 1: Original (but ensure RGB)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    img.save(tmp.name, "JPEG", quality=95)
                    variants.append(tmp.name)

                # Variant 2: Crop bottom 30% (where MRZ usually is)
                bottom_crop = img.crop((0, int(height * 0.7), width, height))
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    bottom_crop.save(tmp.name, "JPEG", quality=95)
                    variants.append(tmp.name)

                # Variant 3: Enhanced contrast
                enhancer = ImageEnhance.Contrast(img)
                enhanced = enhancer.enhance(2.0)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    enhanced.save(tmp.name, "JPEG", quality=95)
                    variants.append(tmp.name)

                # Variant 4: Grayscale with enhanced contrast (for MRZ)
                gray = ImageOps.grayscale(img)
                enhancer = ImageEnhance.Contrast(gray)
                enhanced_gray = enhancer.enhance(2.5)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    enhanced_gray.save(tmp.name, "JPEG", quality=95)
                    variants.append(tmp.name)

                # Variant 5: Bottom crop + grayscale + contrast
                bottom_gray = ImageOps.grayscale(bottom_crop)
                enhancer = ImageEnhance.Contrast(bottom_gray)
                enhanced_bottom = enhancer.enhance(2.5)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    enhanced_bottom.save(tmp.name, "JPEG", quality=95)
                    variants.append(tmp.name)

                # Variant 6: Increased size (2x) for better OCR
                large = img.resize((width * 2, height * 2), Image.Resampling.LANCZOS)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    large.save(tmp.name, "JPEG", quality=95)
                    variants.append(tmp.name)

        except Exception:
            pass

        return variants

    def _parse_mrz(self, img_path: str) -> dict[str, Any] | None:
        """
        Parse MRZ (Machine Readable Zone) from image using passporteye.
        Tries multiple preprocessing variants for better detection.

        Args:
            img_path: Path to JPEG image

        Returns:
            dict with document_type, attributes, mrz_raw, mrz_valid_score, or None
        """
        logger.debug(f"Parsing MRZ from {img_path}")
        temp_files: list[str] = []

        try:
            # Try original image first
            logger.debug("Trying original image for MRZ detection...")
            try:
                mrz = read_mrz(img_path)
                if mrz:
                    valid_score = (
                        mrz.valid_score if hasattr(mrz, "valid_score") else 0.0
                    )
                    logger.debug(
                        f"Original image MRZ result: valid_score={valid_score}"
                    )
                    if valid_score > 0:
                        logger.info(
                            f"MRZ detected successfully from original image (score={valid_score})"
                        )
                        return self._extract_mrz_data(mrz)
                else:
                    logger.debug("No MRZ detected in original image")
            except Exception as e:
                # Check if it's a tesseract missing error
                error_msg = str(e).lower()
                if "tesseract" in error_msg or "tesseractnotfound" in error_msg:
                    logger.warning(
                        "Tesseract OCR not found. passporteye requires tesseract to be installed. "
                        "Install it with: brew install tesseract (macOS) or apt-get install tesseract-ocr (Linux). "
                        "Skipping MRZ detection and falling back to OCR."
                    )
                    # Continue to try variants, but they'll likely fail too
                else:
                    logger.debug(f"Error reading MRZ from original image: {e}")

            # If original failed, try preprocessed variants
            logger.debug("Trying preprocessed image variants...")
            variants = self._preprocess_image_for_mrz(img_path)
            logger.debug(f"Created {len(variants)} preprocessing variants")
            temp_files.extend(variants)

            best_result = None
            best_score = 0.0
            variant_num = 0

            for variant_path in variants:
                variant_num += 1
                try:
                    logger.debug(
                        f"Trying variant {variant_num}/{len(variants)}: {variant_path}"
                    )
                    try:
                        mrz = read_mrz(variant_path)
                        if not mrz:
                            logger.debug(f"Variant {variant_num}: No MRZ detected")
                            continue

                        valid_score = (
                            mrz.valid_score if hasattr(mrz, "valid_score") else 0.0
                        )
                        logger.debug(
                            f"Variant {variant_num}: MRZ found with score={valid_score}"
                        )

                        # Keep the result with highest valid_score
                        if valid_score > best_score:
                            best_score = valid_score
                            result = self._extract_mrz_data(mrz)
                            if result:
                                best_result = result
                                best_result["mrz_valid_score"] = valid_score
                                logger.debug(
                                    f"Variant {variant_num}: New best result with {len(result.get('attributes', {}))} attributes"
                                )

                    except Exception as e:
                        error_msg = str(e).lower()
                        if "tesseract" in error_msg or "tesseractnotfound" in error_msg:
                            logger.debug(
                                f"Variant {variant_num}: Tesseract not available, skipping"
                            )
                            continue
                        else:
                            logger.debug(f"Variant {variant_num}: Error - {e}")
                            continue

                except Exception as e:
                    logger.debug(f"Variant {variant_num}: Unexpected error - {e}")
                    continue

            # If we got a result with any score > 0, return it
            if best_result and best_result.get("mrz_valid_score", 0) > 0:
                logger.info(
                    f"Best MRZ result: score={best_result.get('mrz_valid_score')}, attributes={len(best_result.get('attributes', {}))}"
                )
                return best_result

            # If we got a result but with low score, still return it (better than nothing)
            if best_result:
                logger.debug(
                    f"Returning MRZ result with low score: {best_result.get('mrz_valid_score')}"
                )
                return best_result

            logger.debug("No MRZ detected in any variant")
            return None

        except Exception as e:
            logger.error(f"Error parsing MRZ: {e}", exc_info=True)
            return None

        finally:
            # Cleanup temp files
            for tmp_file in temp_files:
                try:
                    Path(tmp_file).unlink(missing_ok=True)
                except Exception:
                    pass

    def _extract_mrz_data(self, mrz) -> dict[str, Any] | None:
        """
        Extract data from MRZ object.

        Args:
            mrz: MRZ object from passporteye

        Returns:
            dict with document_type, attributes, mrz_raw, mrz_valid_score
        """
        try:
            valid_score = mrz.valid_score if hasattr(mrz, "valid_score") else 0.0
            mrz_text = str(mrz) if mrz else ""
            logger.debug(
                f"Extracting MRZ data: score={valid_score}, mrz_text length={len(mrz_text)}"
            )

            # Classify document type
            doc_type = "unknown"
            if hasattr(mrz, "type"):
                mrz_type = str(mrz.type)
                logger.debug(f"MRZ type attribute: {mrz_type}")
                if mrz_type == "TD3" or (
                    hasattr(mrz, "document_type") and str(mrz.document_type) == "P"
                ):
                    doc_type = "passport"
                elif mrz_type in ("ID-1", "ID-2"):
                    doc_type = "national_id"

            # Also check for passport type in other attributes
            if doc_type == "unknown":
                if hasattr(mrz, "document_type"):
                    doc_type_str = str(mrz.document_type).strip().upper()
                    logger.debug(f"MRZ document_type attribute: {doc_type_str}")
                    if doc_type_str == "P":
                        doc_type = "passport"

            logger.debug(f"Classified document type: {doc_type}")
            attributes: dict[str, Any] = {}

            # Extract common MRZ fields
            if hasattr(mrz, "number"):
                num = str(mrz.number).strip()
                if num:
                    attributes["document_number"] = num
                    logger.debug(f"Extracted document_number: {num}")
            if hasattr(mrz, "surname"):
                surname = str(mrz.surname).strip()
                if surname:
                    attributes["surname"] = surname
                    logger.debug(f"Extracted surname: {surname}")
            if hasattr(mrz, "names"):
                names = str(mrz.names).strip()
                if names:
                    attributes["given_names"] = names
                    logger.debug(f"Extracted given_names: {names}")
            if hasattr(mrz, "nationality"):
                nationality = str(mrz.nationality).strip()
                if nationality:
                    attributes["nationality"] = nationality
                    logger.debug(f"Extracted nationality: {nationality}")
            if hasattr(mrz, "date_of_birth"):
                dob = mrz.date_of_birth
                if dob:
                    # YYMMDD -> YYYY-MM-DD (assume 19xx or 20xx)
                    try:
                        dob_str = str(dob)
                        logger.debug(f"Raw date_of_birth from MRZ: {dob_str}")
                        if len(dob_str) >= 6:
                            year = int(dob_str[:2])
                            month = int(dob_str[2:4])
                            day = int(dob_str[4:6])
                            # Heuristic: if year > 50, assume 1900s, else 2000s
                            full_year = 1900 + year if year > 50 else 2000 + year
                            # Validate date
                            if 1 <= month <= 12 and 1 <= day <= 31:
                                dob_formatted = f"{full_year:04d}-{month:02d}-{day:02d}"
                                attributes["date_of_birth"] = dob_formatted
                                logger.debug(
                                    f"Extracted date_of_birth: {dob_formatted}"
                                )
                    except (ValueError, IndexError) as e:
                        logger.debug(f"Error parsing date_of_birth: {e}")
                        pass
            if hasattr(mrz, "sex"):
                sex = str(mrz.sex).strip().upper()
                if sex in ("M", "F", "X"):
                    attributes["sex"] = sex
                    logger.debug(f"Extracted sex: {sex}")
            if hasattr(mrz, "expiration_date"):
                exp = mrz.expiration_date
                if exp:
                    # YYMMDD -> YYYY-MM-DD
                    try:
                        exp_str = str(exp)
                        logger.debug(f"Raw expiration_date from MRZ: {exp_str}")
                        if len(exp_str) >= 6:
                            year = int(exp_str[:2])
                            month = int(exp_str[2:4])
                            day = int(exp_str[4:6])
                            # Expiration dates are usually in the future
                            # If year < 50, assume 2000s, else 1900s
                            full_year = 2000 + year if year < 50 else 1900 + year
                            # Validate date
                            if 1 <= month <= 12 and 1 <= day <= 31:
                                exp_formatted = f"{full_year:04d}-{month:02d}-{day:02d}"
                                attributes["expiration_date"] = exp_formatted
                                logger.debug(
                                    f"Extracted expiration_date: {exp_formatted}"
                                )
                    except (ValueError, IndexError) as e:
                        logger.debug(f"Error parsing expiration_date: {e}")
                        pass
            if hasattr(mrz, "country"):
                country = str(mrz.country).strip()
                if country:
                    attributes["issuing_state"] = country
                    logger.debug(f"Extracted issuing_state: {country}")

            logger.debug(f"Total attributes extracted: {len(attributes)}")
            return {
                "document_type": doc_type,
                "attributes": attributes,
                "mrz_raw": mrz_text,
                "mrz_valid_score": valid_score,
            }

        except Exception as e:
            logger.error(f"Error extracting MRZ data: {e}", exc_info=True)
            return None

    def _ocr_text(self, img_path: str) -> str:
        """
        Extract text from image using PaddleOCR.

        Args:
            img_path: Path to JPEG image

        Returns:
            Extracted text as single string
        """
        try:
            logger.debug(f"Running OCR on {img_path}")
            try:
                ocr = self._get_ocr_engine()
            except Exception as e:
                logger.error(f"Failed to initialize OCR engine: {e}")
                logger.warning(
                    "PaddleOCR not available. Install it with: pip install paddleocr"
                )
                return ""

            result = ocr.ocr(img_path, cls=True)

            if not result or not result[0]:
                logger.debug("OCR returned no results")
                return ""

            # Combine all detected text
            text_parts: list[str] = []
            for line in result[0]:
                if line and len(line) >= 2:
                    text_parts.append(str(line[1][0]).strip())

            text = " ".join(text_parts)
            logger.debug(
                f"OCR extracted {len(text)} characters, {len(text_parts)} text blocks"
            )
            return text

        except Exception as e:
            logger.error(f"Error in OCR: {e}", exc_info=True)
            return ""

    def _infer_from_ocr(self, text: str) -> tuple[str, dict[str, Any]]:
        """
        Infer document type and extract fields from OCR text using heuristics.

        Args:
            text: OCR-extracted text

        Returns:
            tuple of (document_type, attributes_dict)
        """
        text_upper = text.upper()
        attributes: dict[str, Any] = {}

        # SSN card detection
        if "SOCIAL SECURITY" in text_upper or "SOCIAL SEC" in text_upper:
            ssn_match = re.search(r"\b(\d{3})-(\d{2})-(\d{4})\b", text)
            if ssn_match:
                area = ssn_match.group(1)
                group = ssn_match.group(2)

                # Validate SSN: reject 000/666/9xx areas and 00/000 groups
                if area not in ("000", "666") and not area.startswith("9"):
                    if group not in ("00", "000"):
                        attributes["ssn"] = f"{area}-{group}-{ssn_match.group(3)}"
                        return ("social_security_card", attributes)

        # Driver's license detection
        if ("DRIVER" in text_upper and "LICENSE" in text_upper) or "DL" in text_upper:
            # Extract DOB pattern
            dob_match = re.search(
                r"\b(0[1-9]|1[0-2])[/-](0[1-9]|[12][0-9]|3[01])[/-](\d{4})\b", text
            )
            if dob_match:
                month, day, year = dob_match.groups()
                attributes["date_of_birth"] = f"{year}-{month}-{day}"

            # Extract expiration date pattern
            exp_match = re.search(
                r"\b(EXP|EXPIRES?)[:\s]+(0[1-9]|1[0-2])[/-](0[1-9]|[12][0-9]|3[01])[/-](\d{4})\b",
                text_upper,
            )
            if exp_match:
                month, day, year = exp_match.groups()[1:]
                attributes["expiration_date"] = f"{year}-{month}-{day}"

            return ("drivers_license", attributes)

        # Passport detection
        if (
            "PASSPORT" in text_upper
            or "PASSEPORT" in text_upper
            or "PASAPORTE" in text_upper
        ):
            doc_type = "passport"

            # Try to extract document number
            # Look for patterns like "Passport No." or "Passport Number"
            passport_num_match = re.search(
                r"(?:PASSPORT|PASSEPORT|PASAPORTE)[\s#:NO\.]*\s*(\d{6,12})",
                text_upper,
            )
            if passport_num_match:
                attributes["document_number"] = passport_num_match.group(1)

            # Extract surname (often appears after "SURNAME" or "NOM" or "APELLIDOS")
            surname_patterns = [
                r"(?:SURNAME|NOM|APELLIDOS)[\s:]*([A-Z]{2,})",
                r"([A-Z]{2,})\s*(?:SURNAME|NOM|APELLIDOS)",
            ]
            for pattern in surname_patterns:
                surname_match = re.search(pattern, text_upper)
                if surname_match:
                    attributes["surname"] = surname_match.group(1).strip()
                    break

            # Extract given names
            given_names_patterns = [
                r"(?:GIVEN\s+NAMES?|PR[ÉE]NOMS?|NOMBRES?)[\s:]*([A-Z\s]{3,})",
            ]
            for pattern in given_names_patterns:
                names_match = re.search(pattern, text_upper)
                if names_match:
                    attributes["given_names"] = names_match.group(1).strip()
                    break

            # Extract date of birth
            dob_patterns = [
                r"(?:DATE\s+OF\s+BIRTH|DATE\s+DE\s+NAISSANCE|FECHA\s+DE\s+NACIMIENTO)[\s:]*(\d{1,2})[\s/]+([A-Z]{3})[\s/]+(\d{4})",
                r"(?:DOB|DOB)[\s:]*(\d{1,2})[/-](\d{1,2})[/-](\d{4})",
            ]
            for pattern in dob_patterns:
                dob_match = re.search(pattern, text_upper)
                if dob_match:
                    # Try to parse date
                    try:
                        if len(dob_match.groups()) == 3:
                            part1, part2, year = dob_match.groups()
                            # Check if part2 is month name or number
                            month_names = {
                                "JAN": 1,
                                "FEB": 2,
                                "MAR": 3,
                                "APR": 4,
                                "MAY": 5,
                                "JUN": 6,
                                "JUL": 7,
                                "AUG": 8,
                                "SEP": 9,
                                "OCT": 10,
                                "NOV": 11,
                                "DEC": 12,
                            }
                            if part2.upper() in month_names:
                                month = month_names[part2.upper()]
                                day = int(part1)
                            else:
                                month = int(part2)
                                day = int(part1)
                            attributes["date_of_birth"] = (
                                f"{year}-{month:02d}-{day:02d}"
                            )
                            break
                    except (ValueError, IndexError):
                        continue

            # Extract expiration date if present
            exp_patterns = [
                r"(?:EXP|EXPIRES?|EXPIRATION)[:\s]+(0[1-9]|1[0-2])[/-](0[1-9]|[12][0-9]|3[01])[/-](\d{4})",
                r"(?:EXP|EXPIRES?)[\s:]*(\d{1,2})[\s/]+([A-Z]{3})[\s/]+(\d{4})",
            ]
            for pattern in exp_patterns:
                exp_match = re.search(pattern, text_upper)
                if exp_match:
                    try:
                        if len(exp_match.groups()) == 3:
                            part1, part2, year = exp_match.groups()
                            month_names = {
                                "JAN": 1,
                                "FEB": 2,
                                "MAR": 3,
                                "APR": 4,
                                "MAY": 5,
                                "JUN": 6,
                                "JUL": 7,
                                "AUG": 8,
                                "SEP": 9,
                                "OCT": 10,
                                "NOV": 11,
                                "DEC": 12,
                            }
                            if part2.upper() in month_names:
                                month = month_names[part2.upper()]
                                day = int(part1)
                            else:
                                month = int(part2)
                                day = int(part1)
                            attributes["expiration_date"] = (
                                f"{year}-{month:02d}-{day:02d}"
                            )
                            break
                    except (ValueError, IndexError):
                        continue

            return (doc_type, attributes)

        # Generic ID detection
        if "IDENTITY" in text_upper or (
            "ID" in text_upper and ("CARD" in text_upper or "DOCUMENT" in text_upper)
        ):
            return ("national_id", attributes)

        return ("unknown", {})
