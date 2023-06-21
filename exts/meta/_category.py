from utils import AluCog, ExtCategory, const

category = ExtCategory(
    name='About',
    emote=const.Emote.KURU,
    description='Meta info',
)


class MetaCog(AluCog):
    def __init__(self, bot):
        super().__init__(bot, category=category)
