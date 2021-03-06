import nltk
from nltk.corpus import movie_reviews, stopwords, wordnet
import string, random, re, sys
from stanford_parser import parser as sp
from jpype import JavaException


def generate_opinion_keywords():
    """Generates a list of opinion keywords, by using a Naive Bayes Classifier 
    to find the words which are most informative in predicting whether a movie
    review is positive or negative"""

    def determine_features(review, featurelist):
        result = {}
        for f in featurelist:
            if f in review:
                result[f] = 1
            else:
                result[f] = 0
        return result

    def words_in_synset(word):
        possible_synsets = wordnet.synsets(word)
        if len(possible_synsets) == 0:
            return word.lower()
        else:
            return [syn.lower() for syn in possible_synsets[0].lemma_names]

    #generate a list 1000 most common words which are not stopwords
    stopword_set = stopwords.words('english')
    words =  movie_reviews.words()
    fdist = nltk.FreqDist(word.lower() for word in movie_reviews.words()
                    if word.lower() not in stopword_set and \
                    word not in string.punctuation)
    featurelist = fdist.keys()[:1000]

    #extend the featurelist with synonyms of the words it contains
    featurelist_with_synset_words = []
    for feature in featurelist:
        featurelist_with_synset_words.extend(words_in_synset(feature))
    
    #separate data into training set and test set, and determine features
    pos_reviews = [([word for word in movie_reviews.words(fileid)], 'pos') for fileid in movie_reviews.fileids('pos')]
    neg_reviews = [([word for word in movie_reviews.words(fileid)], 'neg') for fileid in movie_reviews.fileids('neg')]
    all_reviews = pos_reviews + neg_reviews
    random.shuffle(all_reviews)

    #(features are 1/0 for each word in the featurelist)
    featuresets =[(determine_features(review, featurelist), label) 
                    for review, label in all_reviews]

    nreviews = len(all_reviews)
    ntrain = int(nreviews * .75)
    train, test = featuresets[:ntrain], featuresets[ntrain:]
    classifier = nltk.NaiveBayesClassifier.train(train)
    
    #write the 1000 most informative features to a text file. likely more words
    #than necessary, but it's better to overcache than under cache
    print "Accuracy of bayes classifier is: "
    print nltk.classify.accuracy(classifier, test)
    opinion_keywords = []
    f = open('opinions.txt', 'w')
    for opinion, presence in classifier.most_informative_features(n=len(featurelist)):
        if presence == 1: 
            opinion_keywords.append(opinion) 
            print opinion
        f.write("%s\n" % opinion)

    return opinion_keywords


def load_feature_keywords():
    """returns a dict mapping feature keywords to their relative importance. 
    words are via Zhuang et all. "Movie Review Mining and Summarization" """

    #rank 2 is reserved for proper nouns
    features = {'film': 0,
                'movie': 0,
                'story': 1, 'plot': 1,'script': 1,'storyline': 1,'dialogue': 1,
                'screenplay': 1,'ending': 1,'line': 1,'scene': 1,'tale': 1,
                'character': 3, 'characterization': 3, 'role': 3,
                'fight-scene': 4,'action-scene': 4,'action-sequence': 4,'image': 4,
                'set': 4,'battle-scene': 4,'picture': 4,'scenery': 4,
                'setting': 4,'visual-effects': 4,'color': 4,'background': 4,
                'music': 5, 'score': 5, 'song': 5, 'sound': 5, 'soundtrack': 5, 
                'theme': 5,'special-effects': 6, 'effect': 6, 'CGI': 6, 'SFX':6}

    return features


def load_opinion_keywords(reload=False):
    """Loads a list of opinion keywords from textfile, and maps each to a rank
    corresponding to its place in the "most informative features" list """
    try:
        if reload:
            raise Exception()
        with open('opinions.txt', 'r') as opinions:
            return {word.strip(): i for i, word in enumerate(opinions.readlines()[:100])}
    except:
        print "Generating opinion keywords. Might take a while."
        return generate_opinion_keywords()



def construct_dependency_tree(parsed):
    """Constructs a dependency tree from a list of dependency triplets of the 
    form (relationship, governing word, dependent word)"""

    root = parsed.dependencies_root
    dependencies = set([(rel, gov.text, dep.text) for rel, gov, dep in parsed.dependencies])
    children = [(rel, gov, dep) for (rel, gov, dep) in dependencies if gov == root]
    dependencies = dependencies - set(children)

    remaining_nodes = [nltk.Tree(dep, []) for (rel, gov, dep) in children]
    tree = nltk.Tree(root, remaining_nodes)

    while dependencies != set():
        #find current node and its children
        node = remaining_nodes.pop(0)
        children = [(rel, gov, dep) for (rel, gov, dep) in dependencies if gov == node.node]
        children_nodes = [nltk.Tree(dep, []) for (rel, gov, dep) in children]
        
        #update counting structures
        remaining_nodes.extend(children_nodes)
        node.extend(children_nodes)
        dependencies = dependencies - set(children)
    return tree

def val_in_tree(tree, val):
    """Given a nltk.Tree, returns True if val is in tree, False otherwise"""
    if (tree.node == val):
        return True
    for child in tree:
        if val_in_tree(child, val):
            return True
    return False

def dist_to_root(tree, val):
    """Given a value in a tree, return distance from the value to the root"""
    if tree.node == val:
        return 0
    for child in tree:
        if val_in_tree(child, val):
            return 1 + dist_to_root(child, val)

def dist_btwn_feature_and_opinion(feature, opinion, sentence, parser):
    """
    Finds the distance between feature/opinion in a sentence, as determined by
    the dependency graph of the sentence. This distance is not the same as the 
    linear distance between 2 words in a sentence. 

    eg, if the sentence is "the movie is very good", the dependencies are:
    det(movie, the)
    nsubj(good, movie)
    cop(good, is)
    advmod(good, very)
    ... so the distance between "good" (opinion) and "movie" (feature) is 1.
    """

    parsed = parser.parseToStanfordDependencies(sentence)
    tree = construct_dependency_tree(parsed)
    subtrees = tree.subtrees(filter=lambda t: val_in_tree(t,feature) and val_in_tree(t,opinion))

    smallest_tree, height = None, 10000
    for subtree in subtrees:
        if subtree.height() < height:
            smallest_tree = subtree
            height = subtree.height()
    distance = dist_to_root(smallest_tree, feature) + dist_to_root(smallest_tree, opinion)
    return distance

def open_file_as_sentences(filename, features, opinions):
    """Opens a text file and returns it as a list of tokens"""

    f = open(filename, 'r').read()
    sentences = [sent.split(' ') for sent in nltk.tokenize.sent_tokenize(f)]
    return sentences

def find_proper_nouns(sentence):
    """Returns a list of proper nounds in a sentence """
    if type(sentence) == list:
        sentence = string.join(sentence[1:], ' ')
        
    regex = re.compile('[A-Z][a-z]+')
    return [word.strip(string.punctuation) for word in regex.findall(sentence)]


def find_summary_sentence(parser, fileid=None, localfile=None):
    """Finds the summary sentence for a body of text, specified by fileid or by
    localfile. fileid is accessed by NLTK.corpus.movie_reviews; localfile is 
    a path to a non-NLTK text file"""

    #load feature/opinion keywords and their respective ranks
    opinion_ranks = load_opinion_keywords()
    feature_ranks = load_feature_keywords()
    proper_noun_rank = 2
    
    #convert feature/opinions words to set, for quickly checking membership
    feature_words = set(feature_ranks.keys())
    opinion_words = set(opinion_ranks.keys())

    #load movie review as a list of sentence. (each sent is a list of words)
    if fileid and (not localfile):
        source = movie_reviews.sents(fileid)
    elif (not fileid) and localfile:
        source = open_file_as_sentences(localfile, feature_words, opinion_words)
    else:
        print "Please enter an nltk fileid, or the name of a local textfile"
        return

    #filter review for sentences containing a feature and an opinion
    summary_sents = [[word.rstrip(string.punctuation) for word in sent 
                        if word.rstrip(string.punctuation) != ''] 
                        for sent in source
                        if (set(sent) & opinion_words != set()) and 
                        ((set(sent) & feature_words != set()) or 
                            len(find_proper_nouns(sent)) > 0)]

    summary_sents_with_feature_opinion_dist = []
    for sent in summary_sents:
        try:
            feature, feature_rank = None, 10000
            opinion, opinion_rank = None, 10000
            sent_str = string.join(sent, ' ')
            proper_nouns = set(find_proper_nouns(sent)) #unique to each sentence

            #find the best opinion/feature in the sentence
            for word in sent:
                if (word in opinion_words) and opinion_ranks[word] < opinion_rank:
                    opinion = word
                    opinion_rank = opinion_ranks[word]
                elif (word in feature_words) and feature_ranks[word] < feature_rank:
                    feature = word
                    feature_rank = feature_ranks[word]
                elif (word in proper_nouns) and proper_noun_rank < feature_rank :
                    feature = word
                    feature_rank = proper_noun_rank

            #keep track of distance btwn feature/opinion for each sentence
            if feature and opinion:
                distance = dist_btwn_feature_and_opinion(feature, opinion, sent_str, parser)
                summary_sents_with_feature_opinion_dist.append((distance, sent_str))
        except JavaException:
            # print "Failure: sentence is too long (len = %i)" % len(sent)
            pass
        except AssertionError:
            # print "Failure: could not find root"
            pass

    #best summary sentences is the one with closest feature/opinion
    summary_sents_with_feature_opinion_dist.sort()
    if len(summary_sents_with_feature_opinion_dist) > 0:
        return summary_sents_with_feature_opinion_dist[0][1]
    else:
        return None


if __name__ == '__main__':
    parser = sp.Parser()
    if len(sys.argv) > 1:
        for fname in sys.argv[1:]:
            print "\nReview: %s" % fname
            print "Summary: %s\n" % find_summary_sentence(parser, localfile=fname)
    else:
        for fileid in movie_reviews.fileids():
            print "\nReview:", fileid
            print "Summary:\n", find_summary_sentence(parser, fileid=fileid)
