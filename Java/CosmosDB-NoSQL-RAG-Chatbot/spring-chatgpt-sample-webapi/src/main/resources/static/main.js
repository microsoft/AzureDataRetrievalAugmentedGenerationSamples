const CONTEXT_MESSAGE_COUNT = 5;
const DEFAULT_GREETING_MESSAGE = "Hello! How can I assist you today?";
const API_URL = '/chat/completions';
const API_HEADER = {
  "Content-Type": "application/json",
};

var app = new Vue({
  el: '#main',
  data: {
    chatHistory: {
      data: JSON.parse(localStorage.getItem("chatHistory")) ?? [],
      activeChatId: null,
      job: {}
    }
  },
  created: function () {
    if (this.chatHistory.data.length === 0) {
      this.newChat();
    } else {
      const activeChatId = this.chatHistory.data[this.chatHistory.data.length - 1].id;
      this.openChat(activeChatId);
    }
  },
  methods: {
    parseMarkdown: marked.parse,
    scrollThreadToBottom: function () {
      const chatMessageList = document.getElementById("chat-thread-message-list");
      chatMessageList.scrollTop = chatMessageList.scrollHeight;
    },
    scrollHistoryToTop: function () {
      const chatHistoryList = document.getElementById("chat-history-list");
      chatHistoryList.scrollTop = 0;
    },
    parseTimestamp: function (timestamp) {
      const day = new Date(timestamp);
      const date = `${day.getMonth()+1}/${day.getDate()}/${day.getFullYear()}`;
      const time = day.toLocaleTimeString('en-US', {hour12: true, hour: 'numeric', minute: 'numeric', second: 'numeric'});
      const dateTime = `${date}, ${time}`;

      return dateTime;
    },
    openChat: function (id) {
      this.chatHistory.activeChatId = id;

      setTimeout(() => {
        this.scrollThreadToBottom();
      }, 0);
    },
    newChat: function () {
      const timestamp = new Date().getTime();
      const newChatHistory = {
        id: Math.random().toString(16).slice(2),
        title: "New chat",
        timestamp: timestamp,
        messages: [
          {
            sender: "bot",
            text: DEFAULT_GREETING_MESSAGE,
            timestamp: timestamp
          }
        ]
      }

      this.chatHistory.data.push(newChatHistory);
      this.chatHistory.activeChatId = newChatHistory.id;

      this.saveChatHistory();

      setTimeout(() => {
        this.scrollHistoryToTop();
      }, 0);
    },
    sendMessage: function () {
      const message = document.getElementById("chat-input-box").value.trim();
  
      if (message === "") {
        return;
      }
  
      document.getElementById("chat-input-box").value = "";
      const activeChat = this.chatHistory.data.find(chat => chat.id === this.chatHistory.activeChatId);
      activeChat.messages.push({
        sender: "human",
        text: message,
        timestamp: new Date().getTime()
      });
  
      if (activeChat.title === "New chat") {
        activeChat.title = message;
      }

      this.saveChatHistory();
      this.addJob(activeChat.id);

      setTimeout(() => {
        this.scrollThreadToBottom();
      }, 0);
    },
    addJob: async function (id) {
      this.chatHistory.job[id] = this.chatHistory.job[id] ?? [];
      const currentChat = this.chatHistory.data.find(chat => chat.id === id);
      const requestId = Math.random().toString(16).slice(2);
      this.chatHistory.job[id].push(requestId);
      const messages = currentChat.messages.slice(1).slice(0 - CONTEXT_MESSAGE_COUNT).map(message => {
        return {
          content: message.text,
          role: message.sender === "bot" ? "assistant" : "user"
        }
      });
      const response = await fetch(API_URL, {
        method: 'POST',
        headers: API_HEADER ?? {},
        body: JSON.stringify({ messages })
      });

      try {
        const data = await response.json();
        currentChat.messages.push({
          sender: "bot",
          text: data.choices[0].message.content,
          timestamp: new Date().getTime()
        });

        this.saveChatHistory();
      } finally {
        const jobIndex = this.chatHistory.job[id].findIndex(job => job === requestId);
        this.chatHistory.job[id].splice(jobIndex, 1);
        if (this.chatHistory.job[id].length === 0) {
          delete this.chatHistory.job[id];
        }
      }

      setTimeout(() => {
        this.scrollThreadToBottom();
      }, 0);
    },
    removeChat: function (id) {
      const index = this.chatHistory.data.findIndex(chat => chat.id === id);
      this.chatHistory.data.splice(index, 1);
      if (this.chatHistory.activeChatId === id) {
        if (this.chatHistory.data.length > 0) {
          this.chatHistory.activeChatId = this.chatHistory.data[0].id;
        } else {
          this.newChat();
        }
      }

      this.saveChatHistory();

      setTimeout(() => {
        this.scrollThreadToBottom();
      }, 0);
    },
    pressToSendMessage: function (event) {
      if (event.keyCode === 13 && event.ctrlKey) {
        this.sendMessage();
        event.preventDefault();

        return false;
      }
    },
    saveChatHistory: function () {
      const chatHistory = JSON.stringify(this.chatHistory.data);
      localStorage.setItem("chatHistory", chatHistory);
    }
  }
});