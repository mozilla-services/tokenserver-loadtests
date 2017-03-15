""" Molotov-based test.
"""
import time
import uuid
import random
from urllib.parse import urljoin

from molotov import scenario
import browserid.jwt
from browserid.tests.support import make_assertion


ONE_YEAR = 60 * 60 * 24 * 365


# We use a custom mockmyid site to synthesize valid assertions.
# It's hosted in a static S3 bucket so we don't swamp the live mockmyid server.
MOCKMYID_DOMAIN = "mockmyid.s3-us-west-2.amazonaws.com"
MOCKMYID_PRIVATE_KEY = browserid.jwt.DS128Key({
    "algorithm": "DS",
    "x": "385cb3509f086e110c5e24bdd395a84b335a09ae",
    "y": "738ec929b559b604a232a9b55a5295afc368063bb9c20fac4e53a74970a4db795"
         "6d48e4c7ed523405f629b4cc83062f13029c4d615bbacb8b97f5e56f0c7ac9bc1"
         "d4e23809889fa061425c984061fca1826040c399715ce7ed385c4dd0d40225691"
         "2451e03452d3c961614eb458f188e3e8d2782916c43dbe2e571251ce38262",
    "p": "ff600483db6abfc5b45eab78594b3533d550d9f1bf2a992a7a8daa6dc34f8045a"
         "d4e6e0c429d334eeeaaefd7e23d4810be00e4cc1492cba325ba81ff2d5a5b305a"
         "8d17eb3bf4a06a349d392e00d329744a5179380344e82a18c47933438f891e22a"
         "eef812d69c8f75e326cb70ea000c3f776dfdbd604638c2ef717fc26d02e17",
    "q": "e21e04f911d1ed7991008ecaab3bf775984309c3",
    "g": "c52a4a0ff3b7e61fdf1867ce84138369a6154f4afa92966e3c827e25cfa6cf508b"
         "90e5de419e1337e07a2e9e2a3cd5dea704d175f8ebf6af397d69e110b96afb17c7"
         "a03259329e4829b0d03bbc7896b15b4ade53e130858cc34d96269aa89041f40913"
         "6c7242a38895c9d5bccad4f389af1d7a4bd1398bd072dffa896233397a",
})


# There are three different kinds of test, one of which is randomly
# selected for each run:
#
#    - get a token for a previously-seen user
#    - get a token for a never-before-seen user
#    - fail to get a token using an invalid assertion
#
# The first is the default operation and by far the most likely.
# The below options control what percentage of the requests are each
# of the other types.

PERCENT_NEW_USER = 0.3  # yes, it really is that low, based on prod traffic
PERCENT_BAD_USER = 1.0
SERVER_URL = 'https://token.stage.mozaws.net'
SERVER_ENDPOINT = urljoin(SERVER_URL, '/1.0/sync/1.5')
AUDIENCE = SERVER_URL.rstrip('/')


@scenario(PERCENT_BAD_USER)
async def test_bad_assertion(session):
    uid = random.randint(1, 1000000)
    # Try to get a token using an invalid assertion.
    # Obviously, this should result in a 401.
    if _flip_a_coin(25):
        # expired assertion
        assertion = _make_assertion(
            "{uid}@{host}".format(uid=uid, host=MOCKMYID_DOMAIN),
            exp=int(time.time() - ONE_YEAR) * 1000
        )
    elif _flip_a_coin(25):
        # email/issuer mismatch
        assertion = _make_assertion(
            "{uid}@hotmail.com".format(uid=uid)
        )
    elif _flip_a_coin(25):
        # invalid issuer privkey
        assertion = _make_assertion(
            "{uid}@{host}".format(uid=uid, host=MOCKMYID_DOMAIN),
            issuer="api.accounts.firefox.com"
        )
    else:
        # invalid audience
        assertion = _make_assertion(
            "{uid}@{host}".format(uid=uid, host=MOCKMYID_DOMAIN),
            audience="http://123done.org"
        )
    await _do_token_exchange(session, assertion, 401)


@scenario(PERCENT_NEW_USER)
async def test_new_user(session):
    # Get a token for a never-before-seen user account.
    uid = str(uuid.uuid1())
    email = "loadtest-{uid}@{host}".format(uid=uid, host=MOCKMYID_DOMAIN)
    await _do_token_exchange(session, _make_assertion(email))


@scenario(100 - (PERCENT_NEW_USER + PERCENT_BAD_USER))
async def test_old_user(session):
    # Get a token for an "existing" user account.
    # There's no guarantee it will actually exist, but we pull from a
    # fixed pool of user ids so they should get created and persist
    # over time.
    uid = random.randint(1, 1000000)
    email = "user{uid}@{host}".format(uid=uid, host=MOCKMYID_DOMAIN)
    await _do_token_exchange(session, _make_assertion(email))


def _make_assertion(email, **kwds):
    if "audience" not in kwds:
        kwds["audience"] = AUDIENCE
    if "exp" not in kwds:
        kwds["exp"] = int((time.time() + ONE_YEAR) * 1000)
    if "issuer" not in kwds:
        kwds["issuer"] = MOCKMYID_DOMAIN
    if "issuer_keypair" not in kwds:
        kwds["issuer_keypair"] = (None, MOCKMYID_PRIVATE_KEY)
    return make_assertion(email, **kwds)


async def _do_token_exchange(session, assertion, status=200):
    headers = {'Authorization': 'BrowserID %s' % assertion}
    async with session.get(SERVER_ENDPOINT, headers=headers) as resp:
        assert resp.status == status


def _flip_a_coin(percent=50):
    # Return True on 'percent' percent of calls.
    return (random.random() * 100) < percent
