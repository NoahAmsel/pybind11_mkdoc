import re
import warnings
from itertools import chain

def warning_on_one_line(message, category, filename, lineno, file=None, line=None):
    return ' %s:%s: %s:%s\n' % (filename, lineno, category.__name__, message)
warnings.formatwarning = warning_on_one_line

class DoxygenCommand:
    def __init__(self, tag, *synonyms):
        self.tag = tag
        self.synonyms = [tag] + list(synonyms)

    def tag_regex(self):
        """
        Builds regex that matches `@tag` or `\\tag`.
        """
        return r'[\\@](?:{tags})'.format(tags="|".join(self.synonyms))

    def before_regex(self):
        pass

    def after_regex(self):
        pass

    def translate_n(self, text):
        return re.subn(self.before_regex(), self.after_regex(), text)

    def translate(self, text):
        return self.translate_n(text)[0]

class DoxygenCustomFormatCommand(DoxygenCommand):
    def __init__(self, tag, *synonyms, format_regex=None):
        assert(format_regex is not None)
        super().__init__(tag, *synonyms)
        self.__after_regex = format_regex

    def after_regex(self):
        return self.__after_regex

class DoxygenVisualEnhancement(DoxygenCustomFormatCommand):
    def before_regex(self):
        # TODO: should a one-word argument be defined as `\S+`?
        return r'{tag}\s+(?P<word>\S+)'.format(tag=self.tag_regex())

class DoxygenHtmlCommand(DoxygenCustomFormatCommand):
    """
    Command of the form <command> text <\\command>
    """
    def before_regex(self, tag_name=None):
        if tag_name is None:
            tag_name = self.tag
        # Must be `[\w\W]*?` and not `[\w\W]*` to handle cases like `<tag> match1 </tag> <tag> match2 </tag>`, which requires lazy matching.
        # Not that this does not a tag being nested inside itself like this `<tag> <tag> breaks </tag> </tag>`
        return r'<{tag}>([\w\W]*?)</{tag}>'.format(tag=tag_name)

    def translate_n(self, text):
        count = 0
        for tag_name in chain(map(str.lower, self.synonyms), map(str.upper, self.synonyms)):
            text, delta_count = re.subn(self.before_regex(tag_name), self.after_regex(), text)
            count += delta_count
        return text, count

class DoxygenSection(DoxygenCommand):
    """
    Command of the form `\\command { paragraph }`.

    Transformed into
    ```
    Command:
        { paragraph }
    ```
    """
    def __init__(self, tag, *synonyms, title=None, indent=' '*4, next_lines_extra_indent=True, hidden=False):
        self.indent = indent
        super().__init__(tag, *synonyms)
        self.title = title if title else self.tag.capitalize()
        self.next_lines_extra_indent = next_lines_extra_indent
        self.hidden=hidden

    def before_regex(self):
        return r'{tag}(:?\s+(?P<body>[\w\W]*))?'.format(tag=self.tag_regex())

    def after_regex(self):
        return r'{indent}\g<body>'.format(indent=self.indent)

    def title_line(self):
        return "{title}:\n".format(title=self.title)

    def translate_n(self, section, include_title):
        """
        Attempts to reformat a doxygen section according to the rules of the command corresponding to self.

        Args:
            section: A doxygen paragraph/section.
            include_title: Whether to include a title_line, assuming there's a match.

        Returns:
            If there's a match, returns the reformatted section. Otherwise, returns `None`.
        """

        match = re.match(self.before_regex(), section)
        if match:
            if self.hidden:
                translation = ""
            else:
                translation = match.expand(self.after_regex())
                next_line_indent = (2 if self.next_lines_extra_indent else 1) * self.indent
                translation = re.sub(r"\n\s*", r"\n{indent}".format(indent=next_line_indent), translation)
                if include_title:
                    translation = "\n" + self.title_line() + translation
            return translation, 1
        else:
            return section, 0

class DoxygenUntitledSection(DoxygenSection):
    """
    Transformed into just 
    ```
    { paragraph }
    ```
    """
    def __init__(self, tag, *synonyms, hidden=False):
        # overwrite to prohibit passing a title argument
        super().__init__(tag, *synonyms, indent='', hidden=hidden)

    def title_line(self):
        return ""

class DoxygenLabeledSection(DoxygenSection):
    """
    Command of the form `\\command <word> { paragraph }`.

    Transformed into
    ```
    Command:
        <word>: { paragraph }
    ```
    """
    def before_regex(self):
        # TODO: should a one-word argument be defined as `\S+`?
        return r'{tag}(?:\s+(?P<label>\S+))?(?:\s+(?P<body>[\w\W]*))?'.format(tag=self.tag_regex())

    def after_regex(self):
        return r'{indent}\g<label>: \g<body>'.format(indent=self.indent)

class ParamSection(DoxygenLabeledSection):
    def __init__(self):
        super().__init__("param", title="Args")

    def tag_regex(self):
        # Allows for `@param[in,out] description`. See <https://www.doxygen.nl/manual/commands.html#cmdparam>.
        return r'[\\@]{tag}(?:\[(?:in|out|,)*\])?'.format(tag=self.tag)

class DoxygenUnsupportedCommandMixin:
    def warn_if_present(self, result, count):
        if count > 0:
            warnings.warn("Unsupported Doxygen command detected: \\{tag} or @{tag}".format(tag=self.tag), stacklevel=3)
        return result, count

class DoxygenUnsupportedSection(DoxygenSection, DoxygenUnsupportedCommandMixin):
    def translate_n(self, text, include_title):
        return self.warn_if_present(*super().translate_n(text, include_title))

class DoxygenUnsupportedUntitledSection(DoxygenUntitledSection, DoxygenUnsupportedCommandMixin):
    def translate_n(self, text, include_title):
        return self.warn_if_present(*super().translate_n(text, include_title))

class DoxygenUnsupportedVisualEnhancement(DoxygenVisualEnhancement, DoxygenUnsupportedCommandMixin):
    def translate_n(self, text):
        return self.warn_if_present(*super().translate_n(text))

class DoxygenUnsupportedHtmlCommand(DoxygenHtmlCommand, DoxygenUnsupportedCommandMixin):
    def translate_n(self, text):
        return self.warn_if_present(*super().translate_n(text))

class DoxygenTranslator:
    int_types = [
        "int8_t",
        "uint8_t",
        "int16_t",
        "uint16_t",
        "int32_t",
        "uint32_t",
        "int64_t",
        "uint64_t",
        "ssize_t",
        "size_t"
    ]

    string_types = [
        "const char *",
        "const char16_t *",
        "const char32_t *",
        "const wchar_t *",
        "std::string",
        "std::u16string",
        "std::u32string",
        "std::wstring"
    ]

    list_types = ["std::vector", "std::deque", "std::list", "std::array", "std::valarray"]
    set_types = ["std::set", "std::unordered_set"]
    dict_types = ["std::map", "std::unordered_map"]
    tuple_types = ["std::pair", "std::tuple"]
    optional_types = ["std::optional", "std::experimental::optional", "boost::optional"]
    pointer_types = ["std::unique_ptr", "std::shared_ptr"]

    type_substitutions = {
        # See <https://pybind11.readthedocs.io/en/stable/advanced/cast/overview.html>:
        "true": "True",
        "false": "False",
        r'|'.join(("std::nullopt", "boost::none")): "None",
        "double": "float",
        r'|'.join(int_types): "int",   # int8_t, uint8_t, ... => int
        r'|'.join(string_types): "str",    # std::string, std::wstring, ... => str
        r'|'.join(list_types): "List",
        r'|'.join(set_types): "Set",
        r'|'.join(dict_types): "Dict",
        r'|'.join(tuple_types): "Tuple",
        r'|'.join(optional_types): "Optional",
        r'|'.join(pointer_types): "Pointer",
        # See <https://pybind11.readthedocs.io/en/stable/advanced/exceptions.html>:
        "std::exception": "RuntimeError",
        "std::bad_alloc": "MemoryError",
        r'|'.join((
            "std::domain_error",
            "std::length_error",
            "std::invalid_argument",
            "std::range_error",
            "pybind11::value_error")): "ValueError",
        r'|'.join((
            "std::out_of_range",
            "pybind11::index_error")): "IndexError",
        "std::overflow_error": "OverflowError",
        "pybind11::stop_iteration": "StopIteration",
        "pybind11::key_error": "KeyError"
    }

    template_types = ["List", "Set", "Dict", "Tuple", "Optional", "Pointer"]

    def __init__(self, return_includes_type_tag=False, translate_scope_operator=True, hide_tparam=True):
        # These will be tried in order. If there's a match we skip the rest, so put the most common ones first
        self.section_types = [
            ParamSection(),
            DoxygenLabeledSection("return", title="Returns", next_lines_extra_indent=False) if return_includes_type_tag else DoxygenSection("return", title="Returns", next_lines_extra_indent=False),
            DoxygenUntitledSection("brief", "short"),
            DoxygenLabeledSection("tparam", title="Type parameter (C++ only)", hidden=hide_tparam),
            DoxygenLabeledSection("retval", title="Returns"),
            DoxygenLabeledSection("exception", "throw", "throws", title="Raises"),
            DoxygenUnsupportedUntitledSection("overload"),
            DoxygenSection("remark", "note", title="Notes"),
            DoxygenSection("see", "sa", title="See also"),
            DoxygenSection("author", "authors"),
            DoxygenSection("copyright"),
            DoxygenSection("date"),
            DoxygenSection("details"),
            DoxygenSection("extends"),
            DoxygenUnsupportedSection("ingroup", title="In Group"),
        ]

        self.visual_commands = [
            DoxygenVisualEnhancement("a", "e", "em", format_regex=r'*\1*'),
            DoxygenVisualEnhancement("b", format_regex=r'**\1**'),
            DoxygenVisualEnhancement("c", format_regex=r'``\1``'),
            DoxygenHtmlCommand("b", format_regex=r'**\1**'),
            DoxygenHtmlCommand("em", format_regex=r'*\1*'),
            DoxygenHtmlCommand("tt", format_regex=r'``\1``'),
            DoxygenUnsupportedVisualEnhancement("ref", format_regex=r'\\ref \1'),
            DoxygenUnsupportedHtmlCommand("pre", format_regex=r"\n```\1\n```\n"),
            DoxygenUnsupportedHtmlCommand("li", format_regex=r"\n- \1")
        ]

        if translate_scope_operator:
            # `namespace::function` => `namespace.function`
            self.type_substitutions[r'([\w<>\s]*[\w>])::([\w<][\w<>\s]*)'] = r'\1.\2'

        # TODO: add support for @code @endcode, for @f, and for <ul>

    def __call__(self, comment):
        return self.translate(comment)

    def cpp2python(self, text):
        # this loop does most of the common substitutions
        for old, new in self.type_substitutions.items():
            text = re.sub(old, new, text)

        # Turn `List<T>` into `List[T]`. This is trickier than it looks because `T` can itself have a template type,
        # and regex alone can't handle nested brackets.
        depth = 0
        rebracketed_text = ""
        spans = text.split('>')
        for span in spans[:-1]:  # the last span comes *after* the last `>`, so it doesn't need a `>` to be tacked on after it.
            span, delta_depth = re.subn(r'({T})<'.format(T='|'.join(self.template_types)), r'\1[', span)
            depth += delta_depth
            if depth > 0:
                # At the end of span, we're inside a template<> expression. So the '>' means close it off.
                depth -= 1
                rebracketed_text += span + ']'
            else:
                # We're not inside a template<> expression. So '>' in this context is just a regular less-than sign.
                rebracketed_text += span + '>'
        rebracketed_text += spans[-1]

        return rebracketed_text

    def translate(self, comment):
        # Doxygen comment blocks are divided into sections / paragraphs. According to the manual
        # "Paragraphs are delimited by a blank line or by a section indicator." (See <https://www.doxygen.nl/manual/commands.html>.)
        # We also assume each section begins on a new line (which is implied by the manual too).
        # First, we split the comment block into sections
        any_section_indicator_tag = r"|".join(sec_type.tag_regex() for sec_type in self.section_types)
        sections = re.split(r"\n+(?:\n|(?={sec_tag}))".format(sec_tag=any_section_indicator_tag), comment)

        reformated = ""
        previous_section_type = None
        for section in sections:
            section_type_matches = False
            for section_type in self.section_types:
                # If this section is of the same type as the previous section, the two are combined under a single title
                section, section_type_matches = section_type.translate_n(section, include_title=(section_type != previous_section_type))
                if section_type_matches:
                    previous_section_type = section_type
                    break

            if not section_type_matches:
                # If none of the section tags match, then we're in the default case -- a plain paragraph (which doesn't require any reformatting)
                section = "\n" + section

            for visual_command in self.visual_commands:
                section = visual_command.translate(section)

            if not re.fullmatch(r'\s?', section):
                reformated += self.cpp2python(section) + "\n"

        return reformated
