from wagtail import blocks
from wagtail.images.blocks import ImageChooserBlock


class CodeBlock(blocks.StructBlock):
    """
    Code block with syntax highlighting
    """
    language = blocks.ChoiceBlock(
        choices=[
            ('python', 'Python'),
            ('javascript', 'JavaScript'),
            ('bash', 'Bash/Shell'),
            ('html', 'HTML'),
            ('css', 'CSS'),
            ('sql', 'SQL'),
            ('json', 'JSON'),
            ('yaml', 'YAML'),
            ('dockerfile', 'Dockerfile'),
        ],
        default='python'
    )
    code = blocks.TextBlock()

    class Meta:
        template = 'blocks/code_block.html'
        icon = 'code'


class ImageBlock(blocks.StructBlock):
    """
    Image with caption
    """
    image = ImageChooserBlock()
    caption = blocks.CharBlock(required=False)
    attribution = blocks.CharBlock(required=False)

    class Meta:
        template = 'blocks/image_block.html'
        icon = 'image'


class QuoteBlock(blocks.StructBlock):
    """
    Blockquote with author
    """
    quote = blocks.TextBlock()
    author = blocks.CharBlock(required=False)

    class Meta:
        template = 'blocks/quote_block.html'
        icon = 'openquote'
