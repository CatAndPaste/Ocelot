import discord
import asyncio
import requests
import paramiko
import mcrcon
from PIL import Image
from discord.ext import commands
from config import discord_bot, mc_server, ftp, rcon
from mcstatus import MinecraftServer

bot = commands.Bot(command_prefix=discord_bot['prefix'])
server = MinecraftServer.lookup("{}:{}".format(mc_server['ip'], mc_server['port']))
skin_api = 'https://api.mineskin.org/generate/url'
skin_expires = "4777296050804"

def get_status():
    try:
        query = server.query()
    except:
        return "в пустоту (оффлайн)"
    if query.players.online == 0:
        return "на пустой сервер"
    if query.players.online == 1:
        players_cnt = "игрока"
    else:
        players_cnt = "игроков"
    return "на {} {} ({})".format(query.players.online, players_cnt, ", ".join(query.players.names))


async def fetch_online():
    while True:
        await bot.change_presence(status=discord.Status.online,
                                  activity=discord.Activity(type=discord.ActivityType.watching,
                                                            name=get_status()))
        await asyncio.sleep(10)


@bot.command(help='Показывает список пользователей на сервере Minecraft в данный момент')
async def online(ctx):
    try:
        query = server.query()
        latency = server.ping()
    except:
        await ctx.send("Не удалось получить информацию об игроках онлайн, возможно, сервер отключен!")
        return
    await ctx.send("Игроки онлайн ({}): {}\nПинг: {} мс.".format(len(query.players.names),
                                                                 ", ".join(query.players.names), latency))


def validate_skin(url):
    response = requests.head(url)
    if not response.headers.get('content-type') == 'image/png':     # check if jpg will work
        return -1       # invalid
    with Image.open(requests.get(url, stream=True).raw) as im:
        width, height = im.size
        print("Skin dimensions: {}w, {}h".format(width, height))
        if not width == 64 or not (height == 64 or height == 32):
            return -1
        elif height == 64:
            return 0    # classic
        else:
            return 1    # slim


@bot.command(help='Позволяет установить скин на сервере Minecraft. В качестве аргумента должен быть передан никнейм '
                  'игрока, а скин прикреплен к сообщению как изображение .png')
async def skin(ctx, *args):
    if len(args) == 2 and len(ctx.message.attachments) == 0:
        # reset command?
        if args[1].lower() == "reset":
            username = args[0].lower()
            try:
                with mcrcon.MCRcon(rcon['ip'], rcon['password'], port=rcon['port']) as mcr:
                    drop_skin, update_skin = "sr drop skin {}".format(username), \
                                             "sr applyskin {}".format(username)
                    response = mcr.command(drop_skin)
                    print("Command \'{}\' executed, response: \'{}\'".format(drop_skin, response))
                    await asyncio.sleep(0.8)
                    response = mcr.command(update_skin)
                    print("Command \'{}\' executed, response: \'{}\'".format(update_skin, response))
            except:
                await ctx.message.add_reaction("❌")
                await ctx.send("**Не удалось сбросить скин.**\nВозможно, сервер недоступен в данный момент."
                               "Попробуйте позже или свяжитесь с разработчиком.")
            else:
                await ctx.message.add_reaction("👌")
            return
        # no! let's upload the skin!
        else:
            url = args[1]
            skin_type = validate_skin(url)
    # I even uploaded it for you <3
    elif len(args) == 1 and len(ctx.message.attachments) == 1:
        url = ctx.message.attachments[0].url
        skin_type = validate_skin(url)
    # sorry, I forgot the command syntax
    else:
        skin_type = -1

    # skin is invalid:
    if skin_type == -1:
        await ctx.message.add_reaction("❌")
        await ctx.send("**Не удалось установить скин.**\nПрикрепленное к сообщению изображение должно иметь "
                       "**разрешение 64х64 или 64х32**, а в качестве аргумента команды "
                       "!skin должно быть указано имя игрока, которое используется для входа на сервер.")
        return
    # otherwise:
    username = args[0].lower()
    print("Uploading skin to API...")
    response = requests.post(url=skin_api, json={
        "variant": "classic" if skin_type == 0 else "slim",
        "name": username,
        "visibility": 0,
        "url": url
    })
    print("API response: {}".format(response))
    if response.status_code == 200:
        # building skin file structure:
        skin_data = [response.json()['data']['texture']['value'],       # BASE64 skin data from API
                     response.json()['data']['texture']['signature'],   # skin signature from API
                     skin_expires]                                      # basically, the magic number
        filename = "{}.skin".format(username)
        # creating file:
        with open(filename, 'w', encoding="utf-8") as file:
            file.write('\n'.join(skin_data))
        # uploading file to server via sftp:
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(hostname=ftp['hostname'],
                        port=ftp['port'],
                        username=ftp['username'],
                        password=ftp['password'])
            sftp = ssh.open_sftp()
            target = '/plugins/SkinsRestorer/Skins/{}'.format(filename)
            sftp.put(filename, target)
            sftp.close()
            ssh.close()
            print("{} uploaded to server!".format(filename))
        except:
            await ctx.message.add_reaction("❌")
            await ctx.send("**Не удалось установить скин.**\nВозможно, сервер недоступен в данный момент."
                           "Попробуйте позже или свяжитесь с разработчиком.")
            return
        # updating skin on server via rcon:
        try:
            with mcrcon.MCRcon(rcon['ip'], rcon['password'], port=rcon['port']) as mcr:
                com = "sr applyskin {}".format(username)
                response = mcr.command(com)
                print("Command \'{}\' executed, response: \'{}\'".format(com, response))
        except:
            await ctx.send("**Не удалось обновить скин на сервере.**\nЕсли сервер доступен,"
                           "попробуйте перезайти. Если проблема не устранена, свяжитесь с разработчиком.")
    else:
        await ctx.message.add_reaction("❌")
        await ctx.send("**Не удалось установить скин.**\nВозможно, Mineskin API недоступен! Попробуйте позже.")
        return
    await ctx.message.add_reaction("👌")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    raise error


@bot.event
async def on_ready():
    print("Bot is ready!")
    bot.loop.create_task(fetch_online())


bot.run(discord_bot['token'])
