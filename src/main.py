# -*- coding: utf-8 -*-
# 
from os.path import  join, dirname
import re
from anki.hooks import addHook, wrap
from aqt import mw
import anki.find
from aqt.qt import *
from aqt.utils import tooltip, showInfo
from aqt.deckconf import DeckConf
import aqt
import json
from anki.utils import ids2str, intTime
from anki import sched
from anki import schedv2
from anki.collection import _Collection
import copy

addon_path = dirname(__file__)

def getConfig():
    return mw.addonManager.getConfig(__name__)

def startingRefresh():
    refreshConfig()
    if RetroactiveRetiring:
        applyRetirementActions()

def refreshConfig():
    global RetirementDeckName, RetirementTag, RetroactiveRetiring, RealNotifications, RetroNotifications
    config = getConfig()
    RetirementDeckName = config["Retirement Deck Name"]
    RetirementTag = config["Retirement Tag"]
    RetroactiveRetiring = False
    RealNotifications = False
    RetroNotifications = False
    if config["Mass Retirement on Startup"] == 'on':
        RetroactiveRetiring = True
    if config["Real-time Notifications"] == 'on':
        RealNotifications = True
    if config["Mass Retirement Notifications"] == 'on':
        RetroNotifications = True    

def cbStatusCheck(dn,sc, tn, mc):
    if dn.isChecked():
        sc.setEnabled(False)
        tn.setEnabled(False)
        mc.setEnabled(False)
    else:
        sc.setEnabled(True)
        tn.setEnabled(True)
        mc.setEnabled(True)

def addRetirementOpts(self, Dialog):
    row = 7
    wid = QLabel("<b>Card Retirement</b>")
    self.gridLayout_3.addWidget(wid, row, 0, 1, 1)
    row += 1
    self.rInt = QSpinBox()
    self.rInt.setValue(0)
    self.rInt.setMinimum(0)
    self.rInt.setMaximum(99999)
    self.easyBonus.setFixedWidth(60)
    self.revPerDay.setFixedWidth(60)
    self.maxIvl.setFixedWidth(60)
    self.fi1.setFixedWidth(60)
    self.hardFactor.setFixedWidth(60)
    self.rInt.setFixedWidth(60)
   
    self.label_15.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)
    self.label_23.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)
    self.label_34.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)
    self.label_21.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)
    self.gridLayout_3.addWidget(QLabel("Retiring interval (0 = off)"), row, 0, 1, 1)
    self.gridLayout_3.addWidget(self.rInt, row, 1, 1, 1)
    dayLab = QLabel("days")
    dayLab.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed) 
    self.gridLayout_3.addWidget(dayLab, row, 2, 1, 1)
    row += 1
    wid = QLabel("Retirement actions")
    self.gridLayout_3.addWidget(wid, row, 0, 1, 1)

    self.dn = QCheckBox("Delete")
    sep = QFrame()
    sep.setFrameShape(QFrame.VLine)
    sep.setStyleSheet("color: grey;")
    self.sc = QCheckBox("Suspend")
    self.tn = QCheckBox("Tag")
    self.mc = QCheckBox("Move")
    self.dn.setToolTip("WARNING: Applies on a per-note basis; all related cards will be deleted.")
    self.sc.setToolTip("Applies on a per-card basis.")
    self.tn.setToolTip("Applies on a per-note basis; all related cards will be tagged.")
    self.mc.setToolTip("Applies on a per-card basis.")
    self.dn.clicked.connect(lambda: cbStatusCheck(self.dn, self.sc, self.tn, self.mc))
    layout = QHBoxLayout()
    layout.setContentsMargins(0,0,0,0)
    layout.setSpacing(5)
    layout.addWidget(self.dn)
    layout.addWidget(sep)
    layout.addWidget(QLabel("<span>&nbsp;</span>"))
    layout.addWidget(self.sc)
    layout.addWidget(self.tn)
    layout.addWidget(self.mc)
    layout.addStretch()
    self.gridLayout_3.addLayout(layout, row, 1, 1, 2)

def saveRetirement(self):
    c = self.conf['new']
    f = self.form
    c['retiringInterval'] = f.rInt.value()
    c['retirementActions'] = {'delete' : f.dn.isChecked(), 'suspend' : f.sc.isChecked(), 'tag' :f.tn.isChecked(), 'move' : f.mc.isChecked()}

def loadRetirement(self):
   
    c = self.conf['new']
    f = self.form
    if 'retiringInterval' not in c:
        c['retiringInterval'] = 0
    if 'retirementActions' not in c:
        c['retirementActions'] = {'delete' : False, 'suspend' : True, 'tag' : True, 'move' : False}
    f.rInt.setValue(c['retiringInterval'])
    f.dn.setChecked(c['retirementActions']['delete'])
    f.sc.setChecked(c['retirementActions']['suspend'])
    f.tn.setChecked(c['retirementActions']['tag'])
    f.mc.setChecked(c['retirementActions']['move'])
    if f.dn.isChecked():
        f.sc.setEnabled(False)
        f.tn.setEnabled(False)
        f.mc.setEnabled(False)

def raSet(ra):
    for a in ra:
        if ra[a] == True:
            return True
    return False

def getProgressWidget():
    progressWidget = QWidget(None)
    layout = QVBoxLayout()
    progressWidget.setFixedSize(400, 70)
    progressWidget.setWindowModality(Qt.ApplicationModal)
    progressWidget.setWindowTitle("Running Mass Retirement...")
    bar = QProgressBar(progressWidget)
    if isMac:
        bar.setFixedSize(380, 50)
    else:
        bar.setFixedSize(390, 50)
    bar.move(10,10)
    per = QLabel(bar)
    per.setAlignment(Qt.AlignCenter)
    progressWidget.show()
    return progressWidget, bar;

def applyRetirementActions(notes = False, showNotification = True):
    notesToDelete = []
    cardsToMove = []
    suspended = 0
    tagged = 0
    total = 0
    progressWidget, progressBar = getProgressWidget()
    mw.checkpoint('Card Retirement')
    if not notes:
        notes = grabCol()
    checkpointed = False
    progressBar.setMinimum(0)
    progressBar.setMaximum(len(notes))
    count = 0
    for nid in notes:
        count += 1
        if count % 10 == 0:
            progressBar.setValue(count)
            mw.app.processEvents()
        note = mw.col.getNote(nid)
        cards = note.cards()
        
        for card in cards:
            if card.ivl == 0:
                continue
            notesToDelete, cardsToMove, suspended,tagged, total, checkpointed = handleRetirementActions(card, note, notesToDelete, cardsToMove, suspended,tagged, total, checkpointed)
    notification = '' 
    ndl = len(notesToDelete) 
    cml = len(cardsToMove) 
    progressWidget.hide()
    if suspended > 0:
        notification += '- '+ str(suspended) + ' card(s) have been suspended<br>'
    if tagged > 0:
        notification +='- '+  str(tagged) + ' note(s) have been tagged<br>'
    if cml > 0:
        notification +='- '+  str(cml) + ' card(s) have been moved<br>'
        moveToDeck(cardsToMove)
    if ndl > 0:
        notification +='- '+  str(ndl) + ' note(s) have been deleted<br>'
        mw.col.remNotes(notesToDelete)   
    if notification != '' and RetroNotifications:
        mia('<b>'+ str(total) + ' card(s) have been retired:</b><br>' + notification)
    mw.reset()

def setCheckpointed(checkpointed, review):
    if not checkpointed and not review:
            mw.checkpoint("Card Retirement")
    return True

def handleRetirementActions(card, note, notesToDelete, cardsToMove, suspended,tagged, total, checkpointed, review = False):
    conf = mw.col.decks.confForDid(card.odid or card.did)['new']
    if 'retirementActions' in conf and 'retiringInterval' in conf:
        if conf['retiringInterval'] > 0 and raSet(conf['retirementActions']):
            rInt = conf['retiringInterval']
            rAct = conf['retirementActions']
            if card.ivl > rInt:
                total += 1
                if rAct['delete']:
                    checkpointed = setCheckpointed(checkpointed, review)
                    if note.id not in notesToDelete:
                        notesToDelete.append(note.id)
                else:
                    if rAct['suspend']:
                        checkpointed = setCheckpointed(checkpointed, review)
                        if card.queue != -1:
                            suspended += 1
                            card.queue = -1
                            card.flush()

                    if rAct['tag']:
                        checkpointed = setCheckpointed(checkpointed, review)
                        if not note.hasTag(RetirementTag):
                            tagged += 1
                            note.addTag(RetirementTag)
                            note.flush()
                    if rAct['move']:
                        checkpointed = setCheckpointed(checkpointed, review)
                        if card.did != mw.col.decks.id(RetirementDeckName):
                            cardsToMove.append(card.id)
    return notesToDelete, cardsToMove, suspended,tagged, total, checkpointed;

def mia(text):
    showInfo(text ,False,"", "info", "MIA Card Retirement")

def grabCol():
    return anki.find.Finder(mw.col).findNotes('')

def moveToDeck(cids):
    did = mw.col.decks.id(RetirementDeckName)
    from aqt.studydeck import StudyDeck
    if not cids:
        return
    deck = mw.col.decks.get(did)
    if deck['dyn']:
        return
    mod = intTime()
    usn = mw.col.usn()
    scids = ids2str(cids)
    mw.col.sched.remFromDyn(cids)
    mw.col.db.execute("""
update cards set usn=?, mod=?, did=? where id in """ + scids,
                            usn, mod, did)

def checkInterval(self, card, ease):
    workingCard = copy.copy(card)
    notesToDelete = []
    cardsToMove = []
    suspended = 0
    tagged = 0
    total = 0
    checkpointed = False
    note = mw.col.getNote(card.nid)
    notesToDelete, cardsToMove, suspended,tagged, total, checkpointed = handleRetirementActions(card, note, notesToDelete, cardsToMove, suspended,tagged, total, checkpointed, True)
    ndl = len(notesToDelete) 
    cml = len(cardsToMove) 
    if suspended > 0 or tagged > 0 or cml > 0 or ndl > 0:
        last = len(mw.col._undo[2]) - 1
        mw.col._undo[2][last].retirementActions = []
        if cml > 0:
            mw.col._undo[2][last].retirementActions.append('move')
            mw.col._undo[2][last].retirementActions.append(card.did)
            moveToDeck(cardsToMove)
            mw.col.db._db.commit()
        if ndl > 0:
            undoCopy = mw.col._undo
            mw.checkpoint("Card Retirement")
            mw.col._undo.append(undoCopy)
            mw.col.remNotes(notesToDelete)
        if tagged > 0:
            mw.col._undo[2][last].retirementActions.append('tag')
        if(RealNotifications):
            tooltip('The card has been retired.')

def miaRetUndoReview(self):
    lastAdded = len(mw.col._undo[2]) - 1
    if hasattr(self._undo[2][lastAdded], 'retirementActions') and len(self._undo[2][lastAdded].retirementActions) > 0:
        data = self._undo[2]
        wasLeech = self._undo[3]
        c = data.pop()
        if not data:
            self.clearUndo()
        if not wasLeech and c.note().hasTag("leech"):
            c.note().delTag("leech")
            c.note().flush()
        if 'tag' in c.retirementActions:
            c.note().delTag(RetirementTag)
            c.note().flush()
        if c.retirementActions[0] == 'move':
            moveToDeck(c.retirementActions[1], [c.id])
        del c.retirementActions
        c.flush()
        last = self.db.scalar(
            "select id from revlog where cid = ? "
            "order by id desc limit 1", c.id)
        self.db.execute("delete from revlog where id = ?", last)
        self.db.execute(
            "update cards set queue=type,mod=?,usn=? where queue=-2 and nid=?",
            intTime(), self.usn(), c.nid)
        n = 1 if c.queue == 3 else c.queue
        type = ("new", "lrn", "rev")[n]
        self.sched._updateStats(c, type, -1)
        self.sched.reps -= 1
        return c.id
    else:
        ogUndoReview(mw.col)

def miaRetUndo(self):
    
    if self._undo[0] != 1 and self._undo[1] == "Card Retirement" and len(self._undo) > 2:
        tempUndo = self._undo[2]
        self._undoOp()
        self._undo = tempUndo
        self.undo()
    else:
        ogUndo(mw.col)

ogUndoReview = _Collection._undoReview
_Collection._undoReview = miaRetUndoReview

ogUndo = _Collection.undo
_Collection.undo = miaRetUndo

def saveConfig(wid,rdn, rt, retroR, realN, retroN):
    if retroR:
        retroR = 'on'
    else:
        retroR = 'off'
    if realN:
        realN = 'on'
    else:
        realN = 'off'
    if retroN:
        retroN = 'on'
    else:
        retroN = 'off'
    conf = {"Retirement Deck Name" : rdn, "Retirement Tag": rt, "Mass Retirement on Startup": retroR, "Real-time Notifications" : realN, "Mass Retirement Notifications" : retroN }
    mw.addonManager.writeConfig(__name__, conf)
    refreshConfig()
    wid.hide()

def testretire():
    applyRetirementActions()

def openSettings():
    retirementMenu = QDialog(mw)
    retirementMenu.setWindowFlags(Qt.Dialog |Qt.MSWindowsFixedSizeDialogHint)
    l1 = QLabel()
    l1.setText('Retirement Deck Name:')
    l1.setToolTip("The name of the deck retired cards are sent to. Default: “Retired Cards”")
    l1.setFixedWidth(200)
    rdn = QLineEdit()
    rdn.setFixedWidth(229)
    l2 = QLabel()
    l2.setText('Retirement Tag:')
    l2.setToolTip("The tag added to retired cards. Default: “Retired”")
    l2.setFixedWidth(200)
    rt = QLineEdit()
    rt.setFixedWidth(229)
    l3 = QLabel()
    l3.setText('Mass Retirement on Startup:')
    l3.setToolTip("Automatically run mass retirement on profile load.")
    l3.setFixedWidth(210)
    bg1= QGroupBox()  
    bg1b1 = QRadioButton("On")
    bg1b1.setFixedWidth(90)
    bg1b2 = QRadioButton("Off")
    bg1b2.setFixedWidth(100)
    l4 = QLabel()
    l4.setText('Real-time Notifications:')
    l4.setToolTip("Display a notification when a card is retired while reviewing.")
    l4.setFixedWidth(210)
    bg2= QGroupBox() 
    bg2b1 = QRadioButton("On")
    bg2b1.setFixedWidth(90)
    bg2b2 = QRadioButton("Off")
    bg2b2.setFixedWidth(100)
    l5 = QLabel()
    l5.setText('Mass Retirement Notifications:')
    l5.setToolTip("After mass retirement, display a notification detailing results.")
    l5.setFixedWidth(210)
    bg3= QGroupBox() 
    bg3b1 = QRadioButton("On",)
    bg3b1.setFixedWidth(90)
    bg3b2 = QRadioButton("Off")
    bg3b2.setFixedWidth(100)
    applyb =  QPushButton('Apply')
    applyb.clicked.connect(lambda: saveConfig(retirementMenu, rdn.text(), rt.text(),bg1b1.isChecked(),bg2b1.isChecked(),bg3b1.isChecked()))
    applyb.setFixedWidth(100)
    cancelb =  QPushButton('Cancel')
    cancelb.clicked.connect(lambda: retirementMenu.hide())
    cancelb.setFixedWidth(100)
    vh1 = QHBoxLayout()
    vh2 = QHBoxLayout()
    vh3 = QHBoxLayout()
    vh4 = QHBoxLayout()
    vh5 = QHBoxLayout()
    vh6 = QHBoxLayout()
    vh1.addWidget(l1)
    vh1.addWidget(rdn)
    vh2.addWidget(l2)
    vh2.addWidget(rt)
    vh3.addWidget(l3)
    vh3.addWidget(bg1b1)
    vh3.addWidget(bg1b2)
    vh4.addWidget(l4)
    vh4.addWidget(bg2b1)
    vh4.addWidget(bg2b2)
    vh5.addWidget(l5)
    vh5.addWidget(bg3b1)
    vh5.addWidget(bg3b2)
    vh6.addStretch()
    vh6.addWidget(applyb)
    vh6.addWidget(cancelb)
    vh1.addStretch()
    vh2.addStretch()
    vh3.addStretch()
    vh4.addStretch()
    vh5.addStretch()
    vh6.addStretch()
    vl = QVBoxLayout()
    bg1.setLayout(vh3)
    bg2.setLayout(vh4)
    bg3.setLayout(vh5)
    vl.addLayout(vh1)
    vl.addLayout(vh2)
    vl.addWidget(bg1)
    vl.addWidget(bg2)
    vl.addWidget(bg3)
    vl.addLayout(vh6)
    loadCurrent(rt, rdn, bg1b1, bg1b2, bg2b1, bg2b2, bg3b1, bg3b2)
    retirementMenu.setWindowTitle("Retirement Add-on Settings")
    retirementMenu.setWindowIcon(QIcon(join(addon_path, 'mia.png')))
    retirementMenu.setLayout(vl)
    retirementMenu.show()
    retirementMenu.setFixedSize(retirementMenu.size())

def loadCurrent(rt, rdn, bg1b1, bg1b2, bg2b1, bg2b2, bg3b1, bg3b2):
    rt.setText(RetirementTag)
    rdn.setText(RetirementDeckName)
    if RetroactiveRetiring:
        bg1b1.setChecked(True)
    else:
        bg1b2.setChecked(True)
    if RealNotifications:
        bg2b1.setChecked(True)
    else:
        bg2b2.setChecked(True)
    if RetroNotifications:
        bg3b1.setChecked(True)
    else:
        bg3b2.setChecked(True)

def setupMenu():
    addMenu = False
    if not hasattr(mw, 'MIAMenu'):
        mw.MIAMenu = QMenu('MIA | Settings',  mw)
        addMenu = True
    setting = QAction("Retirement Settings", mw.MIAMenu)
    setting.triggered.connect(openSettings)
    mw.MIAMenu.addAction(setting)
    if addMenu:
        mw.form.menuTools.addMenu(mw.MIAMenu)
    addActions = False
    if not hasattr(mw, 'MIAActions'):
        mw.MIAActions = QMenu('MIA | Actions',  mw)
        addActions = True
    action = QAction("Run Mass Retirement", mw.MIAActions)
    action.triggered.connect(testretire)
    mw.MIAActions.addAction(action)
    if addActions:
        mw.form.menuTools.addMenu(mw.MIAActions)

setupMenu()
sched.Scheduler.answerCard = wrap(sched.Scheduler.answerCard, checkInterval)
schedv2.Scheduler.answerCard = wrap(schedv2.Scheduler.answerCard, checkInterval)
aqt.deckconf.DeckConf.loadConf = wrap(aqt.deckconf.DeckConf.loadConf, loadRetirement)
aqt.deckconf.DeckConf.saveConf = wrap(aqt.deckconf.DeckConf.saveConf, saveRetirement, "before")
aqt.forms.dconf.Ui_Dialog.setupUi = wrap(aqt.forms.dconf.Ui_Dialog.setupUi, addRetirementOpts)
addHook("profileLoaded", startingRefresh)

def supportAccept(self):
    if self.addon == os.path.basename(addon_path):
        refreshConfig();

aqt.addons.ConfigEditor.accept = wrap(aqt.addons.ConfigEditor.accept, supportAccept)

